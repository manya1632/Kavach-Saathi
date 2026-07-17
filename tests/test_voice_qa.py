from __future__ import annotations

from unittest.mock import patch

from kavach_saathi.providers.sarvam import SarvamUnavailable

REASONER_TARGET = "kavach_saathi.providers.reasoning.DemoReasoningProvider.structured"
PINECONE_TARGET = "kavach_saathi.providers.vector_index.PineconeIndex._index"
SARVAM_SYNTH_TARGET = "kavach_saathi.providers.sarvam.SarvamClient.synthesize"


class _FakeIndex:
    def upsert(self, *args, **kwargs):
        return None

    def query(self, *args, **kwargs):
        return {"matches": []}


def test_text_query_falls_back_to_deterministic_when_unconfigured(client) -> None:
    """No GEMINI_API_KEY/PINECONE_API_KEY/SARVAM_API_KEY are set in the test
    environment -- the agent must still produce a real (rule-based) answer, honestly
    labeled as a fallback, and use the demo mock audio placeholder rather than crash."""
    response = client.post(
        "/v1/voice/query",
        json={"buyer_id": "B-001", "product_id": "P-001", "text": "Iska fabric kya hai?", "language": "hi"},
    )
    assert response.status_code == 200
    result = response.json()["results"]["voice_qa"]
    assert result["data"]["rag_error"] is not None
    assert result["data"]["audio_key"] == "assets/mock/audio/demo-hi.wav"
    assert "deterministic_keyword_fallback" in [e["source"] for e in result["evidence"] if e["key"] == "rag_context"]


def test_uses_rag_answer_when_pinecone_and_reasoner_available() -> None:
    """Mocked orchestration test: with Pinecone and the reasoner both reachable, the
    agent should use the RAG-grounded answer instead of the deterministic fallback,
    and should upsert the resolved Q&A pair back into the index (the learning loop)."""
    import asyncio

    from kavach_saathi.agents.voice import VoiceAnswer, VoiceQAAgent
    from kavach_saathi.container import get_container
    from kavach_saathi.models import VoiceQueryRequest

    container = get_container()
    fake_answer = VoiceAnswer(
        answer_en="This kurta is 60% cotton, 40% viscose per the verified label.",
        answer_hi="Verified label ke hisaab se yeh kurta 60% cotton, 40% viscose hai.",
        answer_bn="যাচাইকৃত লেবেল অনুযায়ী এই কুর্তা ৬০% কটন, ৪০% ভিসকোজ।",
        answer_mr="पडताळणी केलेल्या लेबलनुसार हा कुर्ता ६०% कापूस, ४०% व्हिस्कोज आहे.",
        answer_gu="ચકાસાયેલ લેબલ મુજબ આ કુર્તા ૬૦% કપાસ, ૪૦% વિસ્કોસ છે.",
        confidence=91,
    )
    agent = VoiceQAAgent(container.service.graphs.specs.context)
    upserted_namespaces: list[str] = []

    class _RecordingIndex(_FakeIndex):
        def upsert(self, *args, **kwargs):
            upserted_namespaces.append(kwargs.get("namespace"))
            return None

    async def run_it():
        with (
            patch(PINECONE_TARGET, return_value=_RecordingIndex()),
            patch.object(agent.context.reasoner, "structured", return_value=fake_answer),
            patch(SARVAM_SYNTH_TARGET, side_effect=SarvamUnavailable("no key in test env")),
        ):
            return await agent.run(VoiceQueryRequest(buyer_id="B-001", product_id="P-001", text="Fabric kya hai?"))

    result = asyncio.get_event_loop().run_until_complete(run_it())
    assert result.data["rag_error"] is None
    assert result.confidence == 91
    assert "resolved_qa" in upserted_namespaces


def test_size_intent_hands_off_without_running_rag() -> None:
    """When the voice graph classifies the question as a size query, size_translator
    runs first and voice_qa should just echo its result, not run its own RAG/reasoner
    pass (matches the existing two-agent routing in orchestration/graph.py)."""
    import asyncio

    from kavach_saathi.agents.voice import VoiceQAAgent
    from kavach_saathi.container import get_container
    from kavach_saathi.models import AgentAction, AgentName, AgentResult, RunStatus, VoiceQueryRequest

    container = get_container()
    agent = VoiceQAAgent(container.service.graphs.specs.context)
    size_result = AgentResult(
        agent=AgentName.SIZE_TRANSLATOR,
        status=RunStatus.COMPLETED,
        confidence=88,
        summary="L is your best size",
        evidence=[],
        actions=[AgentAction(type="select_size", label="Select L")],
        data={"recommended_size": "L"},
        user_message={"en": "We recommend size L", "hi": "L size sahi rahega"},
    )

    async def run_it():
        # If _rag_answer were called here it would hit real Pinecone/Gemini and either
        # error or take real network time -- asserting it's never reached is the point.
        with patch.object(agent, "_rag_answer", side_effect=AssertionError("RAG should not run")):
            return await agent.run(
                VoiceQueryRequest(buyer_id="B-001", product_id="P-001", text="size?"), size_result=size_result
            )

    result = asyncio.get_event_loop().run_until_complete(run_it())
    assert result.user_message["en"] == "We recommend size L"
    assert result.confidence == 88
