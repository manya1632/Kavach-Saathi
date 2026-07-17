from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import select

from kavach_saathi.db.base import SessionLocal
from kavach_saathi.db.models import AgentLog
from kavach_saathi.providers.reasoning import ReasoningUnavailable
from kavach_saathi.providers.vector_index import PineconeUnavailable

REASONER_TARGET = "kavach_saathi.providers.reasoning.DemoReasoningProvider.structured"
PINECONE_TARGET = "kavach_saathi.providers.vector_index.PineconeIndex._index"


def test_falls_back_to_deterministic_when_pinecone_not_configured(client) -> None:
    """No PINECONE_API_KEY is set in the test environment -- the agent must still
    produce a real (rule-based) recommendation, honestly labeled as a fallback, not
    silently pretend the RAG path ran."""
    response = client.post("/v1/size/recommend", json={"buyer_id": "B-001", "product_id": "P-001"})
    assert response.status_code == 200
    body = response.json()
    result = body["results"]["size_translator"]
    assert result["data"]["recommended_size"] == "XL"
    assert result["data"]["rag_error"] is not None
    assert "deterministic_ease_margin_fallback" in [e["source"] for e in result["evidence"]]

    with SessionLocal() as session:
        log = session.execute(
            select(AgentLog)
            .where(AgentLog.agent_name == "size_translator", AgentLog.entity_id == "P-001")
            .order_by(AgentLog.id.desc())
        ).scalars().first()
        assert log.provider == "deterministic_ease_margin_fallback"


def test_uses_rag_recommendation_when_pinecone_and_reasoner_available() -> None:
    """Mocked orchestration test: with Pinecone and the reasoner both reachable, the
    agent should use the RAG-grounded recommendation instead of the fallback."""
    import asyncio

    from kavach_saathi.agents.size import SizeRecommendation, SizeTranslatorAgent
    from kavach_saathi.container import get_container
    from kavach_saathi.models import SizeRecommendRequest

    container = get_container()
    fake_recommendation = SizeRecommendation(
        recommended_size="L",
        reasoning_en="Matches your chest/waist ease and past L purchases fit well.",
        reasoning_hi="Aapke measurements ke hisaab se L size sahi rahega.",
        reasoning_bn="আপনার মাপ অনুযায়ী L সাইজ ঠিক থাকবে।",
        reasoning_mr="तुमच्या मापांनुसार L साइज योग्य राहील.",
        reasoning_gu="તમારા માપ મુજબ L સાઈઝ યોગ્ય રહેશે.",
        confidence=88,
    )

    # All agents share one AgentContext instance (see container.py), so reusing an
    # existing agent's .context gives the same repository/reasoner/media/external.
    agent = SizeTranslatorAgent(container.service.graphs.specs.context)

    async def run_it():
        with (
            patch(PINECONE_TARGET, return_value=_FakeIndex()),
            patch.object(agent.context.reasoner, "structured", return_value=fake_recommendation),
        ):
            return await agent.run(SizeRecommendRequest(buyer_id="B-001", product_id="P-001"))

    result = asyncio.get_event_loop().run_until_complete(run_it())
    assert result.data["recommended_size"] == "L"
    assert result.data["rag_error"] is None
    assert result.confidence == 88


class _FakeIndex:
    def upsert(self, *args, **kwargs):
        return None

    def query(self, *args, **kwargs):
        return {"matches": []}


def test_out_of_chart_recommendation_falls_back_honestly() -> None:
    """If the reasoning model recommends a size that isn't actually in the product's
    chart, the agent must reject it and fall back rather than surface an invalid size."""
    import asyncio

    from kavach_saathi.agents.size import SizeRecommendation, SizeTranslatorAgent
    from kavach_saathi.container import get_container
    from kavach_saathi.models import SizeRecommendRequest

    container = get_container()
    bogus_recommendation = SizeRecommendation(
        recommended_size="XXXL",  # not a real chart size
        reasoning_en="bogus",
        reasoning_hi="bogus",
        reasoning_bn="bogus",
        reasoning_mr="bogus",
        reasoning_gu="bogus",
        confidence=90,
    )
    agent = SizeTranslatorAgent(container.service.graphs.specs.context)

    async def run_it():
        with (
            patch(PINECONE_TARGET, return_value=_FakeIndex()),
            patch.object(agent.context.reasoner, "structured", return_value=bogus_recommendation),
        ):
            return await agent.run(SizeRecommendRequest(buyer_id="B-001", product_id="P-001"))

    result = asyncio.get_event_loop().run_until_complete(run_it())
    assert result.data["recommended_size"] == "XL"  # deterministic fallback, not "XXXL"
    assert "out-of-chart" in result.data["rag_error"]


def test_pinecone_unavailable_is_a_typed_error() -> None:
    from kavach_saathi.config import get_settings
    from kavach_saathi.providers.vector_index import PineconeIndex

    settings = get_settings()
    index = PineconeIndex(settings, index_name=settings.pinecone_size_index)
    try:
        index.upsert([{"id": "x", "text": "y", "metadata": {}}], namespace="buyer_history")
        raise AssertionError("expected PineconeUnavailable")
    except PineconeUnavailable:
        pass


def test_reasoning_unavailable_is_importable() -> None:
    assert issubclass(ReasoningUnavailable, RuntimeError)
