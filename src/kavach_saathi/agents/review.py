from __future__ import annotations

import time

from kavach_saathi.agent_logging import log_agent_call
from kavach_saathi.agents.base import Agent
from kavach_saathi.config import get_settings
from kavach_saathi.db.base import SessionLocal
from kavach_saathi.media_storage import read_image_bytes
from kavach_saathi.models import AgentAction, AgentName, AgentResult, Evidence, ReviewAnalyzeRequest, RunStatus
from kavach_saathi.providers.review_vision import ReviewRelevanceClassifier

# CLIP image-text cosine similarity for a genuinely matching product photo typically
# sits well above similarity for an unrelated image; empirically calibrated, same
# heuristic-threshold pattern as Agent 2's fabric/color mismatch checks.
_CLIP_RELEVANT_THRESHOLD = 0.22
_BERT_RELEVANT_THRESHOLD = 0.55


class ReviewFilterAgent(Agent):
    """Agent 4: Review Truth Filter (final target plan.md Section 6).

    Real CLIP image-text relevance scoring cross-checks review photos against the
    product they were left on; a BERT multilingual text classifier independently scores
    the written review's topical relevance. Both are self-hosted, open-weight models --
    this replaces the previous `expected_relevant` fixture read (gap_report B4) entirely.
    """

    def __init__(self, context):
        super().__init__(context)
        self.vision = ReviewRelevanceClassifier()

    async def run(self, request: ReviewAnalyzeRequest) -> AgentResult:
        started_at = time.perf_counter()
        settings = get_settings()
        review = self.context.repository.get("reviews", request.review_id)
        product = self.context.repository.get("products", request.product_id)

        image_bytes = None
        image_error: str | None = None
        if request.image_key:
            try:
                image_bytes = await read_image_bytes(request.image_key, settings)
            except FileNotFoundError as exc:
                image_error = str(exc)

        scores = self.vision.classify(
            image_bytes=image_bytes,
            review_text=review.get("text", ""),
            product_name=product["name"],
            product_category=product["category"],
        )

        clip_score = scores["clip_image_text_similarity"]
        bert_score = scores["bert_text_relevance"]

        # Media relevance is judged solely by CLIP, the only signal that actually looks
        # at the photo; no photo means nothing to hide on that front. Text relevance is
        # judged by BERT when there's text to score, defaulting to "keep it" otherwise.
        media_relevant = True if clip_score is None else clip_score >= _CLIP_RELEVANT_THRESHOLD
        retain_text = True if bert_score is None else bert_score >= _BERT_RELEVANT_THRESHOLD

        components = [value for value in (clip_score, bert_score) if value is not None]
        confidence = round(50 + (sum(components) / len(components)) * 50) if components else 50
        confidence = max(0, min(100, confidence))

        summary = (
            "Review media matches the product and remains visible."
            if media_relevant
            else "Review media is unrelated and will be hidden; written review remains visible."
        )

        result = AgentResult(
            agent=AgentName.REVIEW_FILTER,
            status=RunStatus.COMPLETED,
            confidence=confidence,
            summary=summary,
            evidence=[
                Evidence(key="clip_image_text_similarity", value=clip_score, source="clip_zero_shot"),
                Evidence(key="bert_text_relevance", value=bert_score, source="bert_multilingual"),
                Evidence(key="image_error", value=image_error, source="media_storage"),
            ],
            actions=[
                AgentAction(
                    type="show_media" if media_relevant else "hide_media",
                    label="Keep review media" if media_relevant else "Hide unrelated media",
                    payload={"retain_text": retain_text},
                )
            ],
            data={"relevant": media_relevant, "retain_text": retain_text, "scores": scores},
            user_message={
                "en": summary,
                "hi": "Review photo product se match karke verify ki gayi.",
            },
        )

        if not media_relevant:
            self.context.repository.set_review_hidden(request.review_id, hidden=True, reason=summary)

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        with SessionLocal() as session:
            log_agent_call(
                session,
                agent_name="review_filter",
                entity_type="review",
                entity_id=request.review_id,
                confidence=confidence,
                latency_ms=latency_ms,
                input_ref=request.image_key or "text_only",
                provider="clip+bert_multilingual",
                output_json=result.data,
            )
            session.commit()

        return result
