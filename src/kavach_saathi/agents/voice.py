from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field

from kavach_saathi.agents.base import Agent
from kavach_saathi.config import get_settings
from kavach_saathi.media_storage import read_image_bytes, write_generated_image
from kavach_saathi.models import AgentName, AgentResult, Evidence, VoiceQueryRequest
from kavach_saathi.providers.reasoning import ReasoningUnavailable
from kavach_saathi.providers.sarvam import SarvamClient, SarvamUnavailable
from kavach_saathi.providers.vector_index import PineconeIndex, PineconeUnavailable

_AUDIO_CONTENT_TYPES = {
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mp3",
    ".m4a": "audio/mp4",
}

_SYSTEM_PROMPT = (
    "You are Kavach Saathi's grounded voice shopping assistant. Answer only from the "
    "supplied commerce evidence -- verified product specs, real buyer reviews, and past "
    "resolved Q&A. Never invent discounts, delivery dates, fabric claims, or return "
    "approvals. If multiple products are supplied, compare them using only their "
    "listed evidence."
)


class VoiceAnswer(BaseModel):
    answer_en: str
    answer_hi: str
    confidence: int = Field(ge=0, le=100)


class VoiceQAAgent(Agent):
    """Agent 5: Grounded Voice Q&A (final target plan.md Section 6).

    RAG over Pinecone (product specs, buyer reviews, and a learning loop of past
    resolved Q&A pairs) grounds a Gemini reasoning call (the plan names Claude; Gemini
    substitutes per project notes). Sarvam AI serves real ASR/TTS -- the plan names
    Bhashini, which requires an institutional SPOC that blocks an individual hackathon
    build; Sarvam is the self-serve free-tier substitute (see project notes). Falls back
    to deterministic keyword answers, honestly labeled, when RAG/reasoning aren't
    configured.
    """

    def __init__(self, context):
        super().__init__(context)
        settings = get_settings()
        self.index = PineconeIndex(settings, index_name=settings.pinecone_qa_index)
        self.sarvam = SarvamClient(settings)

    async def _index_product_knowledge(self, product: dict, reviews: list[dict]) -> None:
        records = [
            {
                "id": f"knowledge-{product['id']}",
                "text": (
                    f"{product['name']} ({product.get('brand', 'unknown brand')}), "
                    f"category {product['category']}, price Rs {product['price']}, "
                    f"specs: {product.get('specs', {})}, "
                    f"return window {product.get('return_window_days', 7)} days, "
                    f"description: {product.get('description', '')}"
                ),
                "metadata": {"product_id": product["id"], "category": product["category"]},
            }
        ]
        for review in reviews[:10]:
            if not review.get("text") or review.get("is_hidden_by_agent"):
                continue
            records.append(
                {
                    "id": f"review-{review['id']}",
                    "text": review["text"],
                    "metadata": {"product_id": product["id"], "rating": review.get("rating", 0)},
                }
            )
        self.index.upsert(records, namespace="product_knowledge")

    async def _rag_answer(
        self, transcript: str, products: list[dict], buyer: dict, sellers: dict[str, dict]
    ) -> tuple[VoiceAnswer, dict]:
        for product in products:
            reviews = self.context.repository.product_reviews(product["id"])
            await self._index_product_knowledge(product, reviews)

        product_ids = [p["id"] for p in products]
        knowledge_matches = self.index.query(
            transcript, namespace="product_knowledge", top_k=6, filter={"product_id": {"$in": product_ids}}
        )
        resolved_qa_matches = self.index.query(
            transcript, namespace="resolved_qa", top_k=3, filter={"product_id": {"$in": product_ids}}
        )

        grounded = {
            "question": transcript,
            "products": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "price": p["price"],
                    "specs": p.get("specs", {}),
                    "return_window_days": p.get("return_window_days", 7),
                    "seller": sellers[p["seller_id"]],
                }
                for p in products
            ],
            "retrieved_knowledge_and_reviews": knowledge_matches,
            "previously_resolved_similar_questions": resolved_qa_matches,
            "buyer_language": buyer.get("language", "hi"),
        }
        answer = await self.context.reasoner.structured(
            system=_SYSTEM_PROMPT,
            prompt=f"Question: {transcript}\nEvidence: {json.dumps(grounded, ensure_ascii=False, default=str)}",
            schema=VoiceAnswer,
            reasoning_effort="low",
        )

        # Learning loop: embed this resolved Q&A pair back into the index so a future
        # semantically similar question retrieves it as grounding context too.
        self.index.upsert(
            [
                {
                    "id": f"qa-{product_ids[0]}-{hashlib.sha1(transcript.encode()).hexdigest()[:12]}",
                    "text": transcript,
                    "metadata": {
                        "product_id": product_ids[0],
                        "answer_en": answer.answer_en,
                        "answer_hi": answer.answer_hi,
                    },
                }
            ],
            namespace="resolved_qa",
        )

        retrieved = {"knowledge_and_reviews": knowledge_matches, "resolved_qa": resolved_qa_matches}
        return answer, retrieved

    def _deterministic_answer(self, transcript: str, products: list[dict]) -> tuple[str, str]:
        lower = transcript.lower()
        primary = products[0]
        specs = primary.get("specs", {})
        if len(products) > 1:
            lines_en = [f"{p['name']}: Rs {p['price']}" for p in products]
            lines_hi = [f"{p['name']}: ₹{p['price']}" for p in products]
            return (
                "Comparing verified listings: " + "; ".join(lines_en) + ".",
                "वेरिफाइड लिस्टिंग की तुलना: " + "; ".join(lines_hi) + "।",
            )
        if any(word in lower for word in ("fabric", "kapda", "material")):
            fabric = specs.get("fabric", "not verified")
            return (
                f"The verified label lists the fabric as {fabric}.",
                f"वेरिफाइड लेबल के अनुसार इसका कपड़ा {fabric} है।",
            )
        if any(word in lower for word in ("return", "wapas", "refund")):
            days = primary.get("return_window_days", 7)
            return (
                f"This product has a {days}-day return window. Return evidence is checked fairly.",
                f"इस प्रोडक्ट पर {days} दिनों की रिटर्न विंडो है। रिटर्न एविडेंस निष्पक्ष तरीके से जाँचा जाता है।",
            )
        return (
            f"{primary['name']} costs Rs {primary['price']} and its verified details are available.",
            f"{primary['name']} की कीमत ₹{primary['price']} है; इसकी वेरिफाइड डिटेल्स उपलब्ध हैं।",
        )

    async def run(self, request: VoiceQueryRequest, size_result: AgentResult | None = None) -> AgentResult:
        settings = get_settings()
        buyer = self.context.repository.get("buyers", request.buyer_id)
        product = self.context.repository.get("products", request.product_id)
        products = [product] + [
            self.context.repository.get("products", pid) for pid in request.compare_product_ids
        ]
        sellers = {p["seller_id"]: self.context.repository.get("sellers", p["seller_id"]) for p in products}

        transcript_source = "text"
        if request.text:
            transcript = request.text
        else:
            try:
                audio_bytes = await read_image_bytes(request.audio_key or "", settings)
                content_type = _AUDIO_CONTENT_TYPES.get(
                    Path(request.audio_key or "").suffix.lower(), "audio/wav"
                )
                transcript = await self.sarvam.transcribe(audio_bytes, request.language, content_type=content_type)
                transcript_source = "sarvam_stt"
            except (SarvamUnavailable, FileNotFoundError):
                transcript = "Mujhe kaunsa size lena chahiye?"
                transcript_source = "sarvam_unavailable_demo_transcript"

        rag_error: str | None = None
        if size_result:
            answer_en = size_result.user_message["en"]
            answer_hi = size_result.user_message["hi"]
            confidence = size_result.confidence
            retrieved: dict = {}
            provider = "size_translator_handoff"
        else:
            try:
                answer, retrieved = await self._rag_answer(transcript, products, buyer, sellers)
                answer_en, answer_hi, confidence = answer.answer_en, answer.answer_hi, answer.confidence
                provider = f"pinecone_rag+{self.context.reasoner.name}"
            except (PineconeUnavailable, ReasoningUnavailable) as exc:
                rag_error = str(exc)
                answer_en, answer_hi = self._deterministic_answer(transcript, products)
                confidence = 94
                retrieved = {}
                provider = "deterministic_keyword_fallback"

        answer_text = answer_hi if request.language == "hi" else answer_en
        try:
            audio_bytes = await self.sarvam.synthesize(answer_text, request.language)
            audio_key = write_generated_image(
                f"generated/audio/{hashlib.sha1(answer_text.encode()).hexdigest()[:16]}.wav",
                audio_bytes,
                settings,
                content_type="audio/wav",
            )
        except SarvamUnavailable:
            lang_suffix = request.language if request.language in ("en", "hi") else "hi"
            audio_key = f"assets/mock/audio/demo-{lang_suffix}.wav"

        return AgentResult(
            agent=AgentName.VOICE_QA,
            confidence=confidence,
            summary=answer_en,
            evidence=[
                Evidence(key="transcript", value=transcript, source=transcript_source),
                Evidence(key="product_ids", value=[p["id"] for p in products], source="catalogue"),
                Evidence(key="rag_context", value=retrieved, source=provider),
                Evidence(key="rag_error", value=rag_error, source="fallback_policy"),
            ],
            data={
                "transcript": transcript,
                "audio_key": audio_key,
                "language": request.language,
                "rag_error": rag_error,
            },
            user_message={"en": answer_en, "hi": answer_hi},
        )
