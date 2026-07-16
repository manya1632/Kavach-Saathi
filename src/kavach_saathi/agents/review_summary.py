from __future__ import annotations

import time

from pydantic import BaseModel, Field

from kavach_saathi.agent_logging import log_agent_call
from kavach_saathi.agents.base import Agent
from kavach_saathi.db.base import SessionLocal
from kavach_saathi.models import AgentName, AgentResult, Evidence, ReviewSummaryRequest, RunStatus
from kavach_saathi.providers.reasoning import ReasoningUnavailable

_SYSTEM_PROMPT = (
    "You are Kavach Saathi's review-truth summarizer. Given a product's real buyer "
    "reviews (star rating + text) and the aggregate photo-verification counts from "
    "Agent 4's real CLIP+BERT check, write a 2-4 sentence natural-language summary of "
    "overall customer sentiment: what most buyers praise, what a minority complain "
    "about, and how the photo-verification result should be read. Ground every claim "
    "in the supplied reviews -- never invent a complaint or praise that isn't actually "
    "represented in them."
)


class ReviewSummary(BaseModel):
    summary: str = Field(description="2-4 sentence natural-language summary of overall customer sentiment")
    confidence: int = Field(ge=0, le=100)


def _deterministic_summary(total: int, average_rating: float, positive_pct: int, negative_pct: int) -> str:
    if total == 0:
        return "No reviews yet for this product."
    tail = f", while {negative_pct}% report issues with quality, fit, or delivery." if negative_pct else "."
    return (
        f"Average rating is {average_rating}/5 across {total} reviews. "
        f"{positive_pct}% rate it 4 stars or higher{tail}"
    )


class ReviewSummaryAgent(Agent):
    """Extends Agent 4 (Review Truth)'s scope with an LLM-generated aggregate summary
    of a product's reviews, grounded in the real seeded review text/ratings and the
    real CLIP+BERT photo-verification counts (repository.review_report()) --
    complements the existing per-review relevance check (ReviewFilterAgent) rather
    than replacing it. Reports as AgentName.REVIEW_FILTER since it's the same "Review
    Truth" identity already shown in the storefront, just a richer aggregate view
    instead of a single-review spot check -- this keeps the app's "8 agents" branding
    intact rather than introducing a 9th agent identity for what's really an extension
    of Agent 4's existing scope.
    """

    async def run(self, request: ReviewSummaryRequest) -> AgentResult:
        started_at = time.perf_counter()
        product = self.context.repository.get("products", request.product_id)
        reviews = self.context.repository.product_reviews(request.product_id)
        report = self.context.repository.review_report(request.product_id)

        total = report["total_reviews"]
        rating_counts = {n: 0 for n in range(1, 6)}
        for review in reviews:
            rating_counts[review["rating"]] = rating_counts.get(review["rating"], 0) + 1
        average_rating = round(sum(r["rating"] for r in reviews) / total, 1) if total else 0.0
        positive_pct = round((rating_counts[5] + rating_counts[4]) / total * 100) if total else 0
        negative_pct = round((rating_counts[1] + rating_counts[2]) / total * 100) if total else 0

        rag_error: str | None = None
        provider_name = "none"
        if total == 0:
            summary_text = "No reviews yet for this product."
            confidence = 50
        else:
            review_lines = "\n".join(f"- {review['rating']}★: {review['text']}" for review in reviews if review["text"])
            prompt = (
                f"Product: {product['name']} ({product['category']})\n"
                f"Total reviews: {total}, average rating: {average_rating}/5\n"
                f"Photo verification: {report['photos_verified']} of {report['photos_submitted']} submitted "
                f"photos verified genuine, {report['photos_flagged']} flagged as mismatched.\n"
                f"Reviews:\n{review_lines}"
            )
            try:
                result = await self.context.reasoner.structured(
                    system=_SYSTEM_PROMPT,
                    prompt=prompt,
                    schema=ReviewSummary,
                    reasoning_effort="low",
                )
                summary_text = result.summary
                confidence = result.confidence
                provider_name = self.context.reasoner.name
            except ReasoningUnavailable as exc:
                rag_error = str(exc)
                summary_text = _deterministic_summary(total, average_rating, positive_pct, negative_pct)
                confidence = 70

        result = AgentResult(
            agent=AgentName.REVIEW_FILTER,
            status=RunStatus.COMPLETED,
            confidence=confidence,
            summary=summary_text,
            evidence=[
                Evidence(key="average_rating", value=average_rating, source="review_aggregate"),
                Evidence(key="rating_breakdown", value=rating_counts, source="review_aggregate"),
                Evidence(key="rag_error", value=rag_error, source="fallback_policy"),
            ],
            data={
                "summary": summary_text,
                "total_reviews": total,
                "average_rating": average_rating,
                "rating_breakdown": rating_counts,
                "photos_submitted": report["photos_submitted"],
                "photos_verified": report["photos_verified"],
                "photos_flagged": report["photos_flagged"],
                "rag_error": rag_error,
            },
            user_message={"en": summary_text},
        )

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        with SessionLocal() as session:
            log_agent_call(
                session,
                agent_name="review_summary",
                entity_type="product",
                entity_id=request.product_id,
                confidence=confidence,
                latency_ms=latency_ms,
                input_ref=f"{total}_reviews",
                provider=provider_name,
                output_json=result.data,
            )
            session.commit()

        return result
