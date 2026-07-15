from __future__ import annotations

import time

from pydantic import BaseModel, Field

from kavach_saathi.agent_logging import log_agent_call
from kavach_saathi.agents.base import Agent
from kavach_saathi.config import get_settings
from kavach_saathi.db.base import SessionLocal
from kavach_saathi.models import AgentAction, AgentName, AgentResult, Evidence, RunStatus, SizeRecommendRequest
from kavach_saathi.providers.reasoning import ReasoningUnavailable
from kavach_saathi.providers.vector_index import PineconeIndex, PineconeUnavailable

_LANGUAGE_NAMES = {"hi": "Hindi", "en": "English", "bn": "Bengali", "mr": "Marathi", "gu": "Gujarati"}

_SYSTEM_PROMPT = (
    "You are Kavach Saathi's cross-seller size translator. Given a buyer's body "
    "measurements, their past purchase history (sizes bought across different brands "
    "and how each one fit), the target product's own size chart, and comparable "
    "brands' size charts retrieved for cross-seller comparison, recommend the single "
    "best size for the target product. You must only recommend a size label that "
    "actually appears in the target product's size chart. Ground your reasoning "
    "explicitly in the retrieved evidence -- never invent a measurement or a past "
    "order that wasn't given to you."
)


class SizeRecommendation(BaseModel):
    recommended_size: str = Field(description="Must be one of the size labels present in the target size chart")
    reasoning_en: str = Field(description="One or two sentence explanation in English")
    reasoning_hi: str = Field(description="The same explanation in Hindi")
    confidence: int = Field(ge=0, le=100)


def _deterministic_recommendation(chart: dict, body: dict) -> str | None:
    for size, measurements in chart.items():
        if (
            measurements.get("chest", 0) >= body.get("chest", 0) + 6
            and measurements.get("waist", 0) >= body.get("waist", 0) + 4
        ):
            return size
    return None


class SizeTranslatorAgent(Agent):
    """Agent 3: Cross-Seller Translator (final target plan.md Section 6).

    RAG over Pinecone -- buyer purchase-history embeddings + brand size-chart deltas --
    grounds a Gemini reasoning call (the plan names Claude; Gemini substitutes per
    project notes, see .env.example) that produces the recommendation. Falls back to
    deterministic ease-margin arithmetic, honestly labeled as a fallback rather than
    disguised as the real answer, when Pinecone/reasoning aren't configured.
    """

    def __init__(self, context):
        super().__init__(context)
        settings = get_settings()
        self.index = PineconeIndex(settings, index_name=settings.pinecone_size_index)

    async def _index_buyer_history(self, buyer_id: str, history: list[dict]) -> None:
        records = []
        for order in history[-10:]:
            if not order.get("fit_feedback") or not order.get("product_id"):
                continue
            try:
                product = self.context.repository.get("products", order["product_id"])
            except Exception:  # noqa: BLE001 - skip orders whose product no longer resolves
                continue
            records.append(
                {
                    "id": f"order-{order['id']}",
                    "text": (
                        f"Bought {product['name']} ({product.get('brand', 'unknown brand')}) "
                        f"size {order.get('size')}, fit feedback: {order['fit_feedback']}"
                    ),
                    "metadata": {
                        "buyer_id": buyer_id,
                        "brand": product.get("brand", ""),
                        "size": order.get("size", ""),
                        "fit_feedback": order["fit_feedback"],
                    },
                }
            )
        self.index.upsert(records, namespace="buyer_history")

    async def _index_brand_charts(self, product: dict, peers: list[dict]) -> None:
        records = []
        for candidate in [product, *peers]:
            chart = candidate.get("size_chart") or {}
            if not chart:
                continue
            sizes = ", ".join(
                f"{size}: chest {m.get('chest')}cm waist {m.get('waist')}cm" for size, m in chart.items()
            )
            brand = candidate.get("brand", "unknown brand")
            records.append(
                {
                    "id": f"chart-{candidate['id']}",
                    "text": f"{brand} size chart for {candidate['category']}: {sizes}",
                    "metadata": {
                        "product_id": candidate["id"],
                        "brand": candidate.get("brand", ""),
                        "category": candidate["category"],
                    },
                }
            )
        self.index.upsert(records, namespace="brand_charts")

    async def _rag_recommend(
        self, buyer: dict, product: dict, chart: dict, body: dict, history: list[dict]
    ) -> tuple[SizeRecommendation, dict]:
        peers = self.context.repository.products_in_category(product["category"], exclude_id=product["id"])
        await self._index_buyer_history(buyer["id"], history)
        await self._index_brand_charts(product, peers)

        buyer_matches = self.index.query(
            f"buyer sizing history for {product['category']} {product.get('brand', '')}",
            namespace="buyer_history",
            top_k=5,
            filter={"buyer_id": buyer["id"]},
        )
        chart_matches = self.index.query(
            f"{product.get('brand', '')} size chart for {product['category']}",
            namespace="brand_charts",
            top_k=5,
            filter={"category": product["category"]},
        )

        language_name = _LANGUAGE_NAMES.get(buyer.get("language", "en"), "English")
        prompt = (
            f"Buyer measurements (cm): {body}\n"
            f"Target product: {product['name']} ({product.get('brand', 'unknown')}), size chart: {chart}\n"
            f"Retrieved buyer purchase history: {buyer_matches}\n"
            f"Retrieved comparable brand size charts: {chart_matches}\n"
            f"Write the Hindi reasoning in natural {language_name} phrasing appropriate for an Indian shopper."
        )
        recommendation = await self.context.reasoner.structured(
            system=_SYSTEM_PROMPT,
            prompt=prompt,
            schema=SizeRecommendation,
            reasoning_effort="low",
        )
        retrieved = {"buyer_history_matches": buyer_matches, "brand_chart_matches": chart_matches}
        return recommendation, retrieved

    async def run(self, request: SizeRecommendRequest) -> AgentResult:
        started_at = time.perf_counter()
        buyer = self.context.repository.get("buyers", request.buyer_id)
        product = self.context.repository.get("products", request.product_id)
        chart = product.get("size_chart", {})
        body = buyer.get("measurements_cm", {})
        history = self.context.repository.buyer_orders(request.buyer_id)
        good_history = [order for order in history if order.get("fit_feedback") == "good"]

        rag_error: str | None = None
        recommendation: SizeRecommendation | None = None
        retrieved: dict = {}

        if chart:
            try:
                candidate, retrieved = await self._rag_recommend(buyer, product, chart, body, history)
                if candidate.recommended_size not in chart:
                    raise ValueError(f"Model recommended an out-of-chart size: {candidate.recommended_size}")
                recommendation = candidate
            except (PineconeUnavailable, ReasoningUnavailable, ValueError) as exc:
                rag_error = str(exc)

        provider = f"pinecone_rag+{self.context.reasoner.name}"
        if recommendation is not None:
            recommended = recommendation.recommended_size
            confidence = recommendation.confidence
            summary = recommendation.reasoning_en
            user_message = {"en": recommendation.reasoning_en, "hi": recommendation.reasoning_hi}
            source = provider
        else:
            recommended = _deterministic_recommendation(chart, body)
            provider = "deterministic_ease_margin_fallback"
            source = provider
            if recommended:
                confidence = min(90, 70 + min(len(good_history), 4) * 4)
                summary = (
                    f"{recommended} is the safest match from measurements and successful "
                    f"purchases (RAG fallback: {rag_error})."
                )
                user_message = {
                    "en": summary,
                    "hi": f"Aapke measurements aur pichhli fitting ke hisaab se {recommended} size sabse safe hai.",
                }
            else:
                confidence = 30
                summary = (
                    "No listed size provides the required ease; ask for measurements or "
                    f"choose another product (RAG fallback: {rag_error})."
                )
                user_message = {"en": summary, "hi": "Is product mein abhi safe size match nahi mila."}

        actions = (
            [AgentAction(type="select_size", label=f"Select {recommended}", payload={"size": recommended})]
            if recommended
            else [AgentAction(type="request_measurements", label="Confirm body measurements")]
        )

        history_evidence = [
            {"product_id": item["product_id"], "size": item.get("size"), "fit": item.get("fit_feedback")}
            for item in good_history[-3:]
        ]

        result = AgentResult(
            agent=AgentName.SIZE_TRANSLATOR,
            status=RunStatus.COMPLETED if recommended else RunStatus.NEEDS_EVIDENCE,
            confidence=confidence,
            summary=summary,
            evidence=[
                Evidence(key="buyer_measurements_cm", value=body, source="buyer_profile"),
                Evidence(key="seller_size_chart", value=chart, source="verified_listing"),
                Evidence(key="successful_history", value=history_evidence, source="order_history"),
                Evidence(key="rag_context", value=retrieved, source=source),
            ],
            actions=actions,
            data={"recommended_size": recommended, "history": history_evidence, "rag_error": rag_error},
            user_message=user_message,
        )

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        with SessionLocal() as session:
            log_agent_call(
                session,
                agent_name="size_translator",
                entity_type="product",
                entity_id=product["id"],
                confidence=confidence,
                latency_ms=latency_ms,
                input_ref=f"buyer={buyer['id']}",
                provider=provider,
                output_json=result.data,
            )
            session.commit()

        return result
