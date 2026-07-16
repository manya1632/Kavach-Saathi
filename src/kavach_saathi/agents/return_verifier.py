from __future__ import annotations

import time

from sqlalchemy import select

from kavach_saathi.agent_logging import log_agent_call
from kavach_saathi.agents.base import Agent
from kavach_saathi.config import get_settings
from kavach_saathi.db.base import SessionLocal
from kavach_saathi.media_storage import read_image_bytes
from kavach_saathi.models import (
    AgentAction,
    AgentName,
    AgentResult,
    Evidence,
    ReturnAnalyzeRequest,
    RunStatus,
)
from kavach_saathi.providers.reasoning import ReasoningUnavailable
from kavach_saathi.providers.return_vision import ReturnVisionVerifier
from kavach_saathi.providers.spec_ocr import EXTRACTION_PROMPT, EXTRACTION_SYSTEM_PROMPT, ExtractedSpec
from kavach_saathi.trust_jobs import compute_buyer_trust_signal, compute_seller_trust_score

# CLIP cosine similarity above this ~= the returned item plausibly is the same
# product as the catalogue photo; same heuristic-threshold pattern as Agent 2's
# fabric/color mismatch checks.
_PRODUCT_MATCH_THRESHOLD = 0.75


def _fabric_roughly_matches(claimed: str | None, extracted: str | None) -> bool:
    if not claimed or not extracted:
        return False
    claimed, extracted = claimed.lower(), extracted.lower()
    return claimed in extracted or extracted in claimed


class ReturnVerifierAgent(Agent):
    """Agent 8: Return Authenticity Verifier (final target plan.md Section 6).

    Extracts real frames from the buyer's return video, compares the best-matching
    frame against the product's real catalogue image via CLIP embedding similarity,
    and reads any visible care label/tag on that frame via the configured multimodal
    reasoning provider (Gemini/Groq; the plan names Claude, see project notes) --
    cross-checked against the product's own listed fabric. Replaces the previous
    `expected_confidence` fixture override (gap_report B5/Y9) with a genuinely
    computed score.
    """

    def __init__(self, context):
        super().__init__(context)
        self.vision = ReturnVisionVerifier()

    async def run(self, request: ReturnAnalyzeRequest) -> AgentResult:
        started_at = time.perf_counter()
        settings = get_settings()
        order = self.context.repository.get("orders", request.order_id)
        product = self.context.repository.get("products", request.product_id)
        reference_bytes = await read_image_bytes(product["media"]["primary"], settings)

        # A multi-seller cart order's arbitrary "first item" (what repository.get()
        # returns) may not be this specific line item -- look up the real seller for
        # the product actually being returned so trust scoring credits/blames the
        # right seller.
        with SessionLocal() as item_session:
            from kavach_saathi.db.models import OrderItem

            order_item = item_session.execute(
                select(OrderItem).where(
                    OrderItem.order_id == request.order_id, OrderItem.product_id == request.product_id
                )
            ).scalars().first()
            item_seller_id = order_item.seller_id if order_item else order["seller_id"]

        video_bytes = await read_image_bytes(request.video_key, settings)
        frames = self.vision.extract_frames(video_bytes, count=5)
        for image_key in request.additional_image_keys:
            frames.append(await read_image_bytes(image_key, settings))

        clip_similarity, best_frame = self.vision.best_match(frames, reference_bytes)
        product_matches = clip_similarity >= _PRODUCT_MATCH_THRESHOLD

        label_error: str | None = None
        extracted = ExtractedSpec(label_visible=False)
        if best_frame is not None:
            try:
                extracted = await self.context.reasoner.structured(
                    system=EXTRACTION_SYSTEM_PROMPT,
                    prompt=EXTRACTION_PROMPT,
                    schema=ExtractedSpec,
                    images=[best_frame],
                )
            except ReasoningUnavailable as exc:
                label_error = str(exc)

        original_fabric = product.get("specs", {}).get("fabric")
        label_matches = bool(extracted.label_visible) and (
            not original_fabric or not extracted.fabric or _fabric_roughly_matches(original_fabric, extracted.fabric)
        )

        history = self.context.repository.buyer_orders(order["buyer_id"])
        clean_history = sum(1 for item in history if item.get("return_outcome") in (None, "approved"))

        score = 20
        score += round(min(1.0, max(0.0, clip_similarity)) * 45)
        score += 20 if label_matches else 0
        score += 15 if extracted.label_visible else 0
        score += min(10, clean_history * 2)
        score = min(100, max(0, score))

        # Non-overlapping confidence policy (plan.md Task 9):
        # 75-100: Approved + schedule pickup
        # 40-74:  More evidence required before deciding
        # 0-39:   Manual hub inspection (never auto-reject the buyer)
        if score >= 75:
            status = RunStatus.COMPLETED
            decision = "approve"
            summary = "Return evidence is consistent; approve and schedule pickup."
            actions = [AgentAction(type="approve_return", label="Approve return and schedule pickup")]
        elif score >= 40:
            status = RunStatus.NEEDS_EVIDENCE
            decision = "request_more_evidence"
            summary = "Evidence is incomplete; please upload one more clear angle before we can decide."
            actions = [AgentAction(type="upload_more_evidence", label="Upload another angle")]
        else:
            status = RunStatus.MANUAL_REVIEW
            decision = "manual_inspection"
            summary = "Confidence is low; sending to hub inspection — we will not auto-reject your return."
            actions = [AgentAction(type="manual_inspection", label="Send to hub inspection")]

        checks = {
            "product_matches": product_matches,
            "clip_similarity": round(clip_similarity, 4),
            "tag_visible": extracted.label_visible,
            "label_matches": label_matches,
            "extracted_fabric": extracted.fabric,
            "claimed_fabric": original_fabric,
        }

        # Persist the decision as a real `returns` row and stamp the order's
        # return_outcome so trust_jobs.py has genuine data to compute from -- this was
        # previously computed and returned to the caller but never written anywhere.
        self.context.repository.record_return_decision(
            request.order_id,
            product_id=request.product_id,
            buyer_id=order["buyer_id"],
            video_key=request.video_key,
            confidence_score=score,
            decision=decision,
        )
        with SessionLocal() as trust_session:
            compute_seller_trust_score(trust_session, item_seller_id)
            compute_buyer_trust_signal(trust_session, order["buyer_id"])
            trust_session.commit()

        result = AgentResult(
            agent=AgentName.RETURN_VERIFIER,
            status=status,
            confidence=score,
            summary=summary,
            evidence=[
                Evidence(key="video_checks", value=checks, source="clip_frame_match+vision_ocr"),
                Evidence(key="frames_examined", value=len(frames), source="opencv_frame_extraction"),
                Evidence(key="label_extraction_error", value=label_error, source="fallback_policy"),
                Evidence(key="clean_order_history", value=clean_history, source="order_history", weight=0.2),
            ],
            actions=actions,
            data={"decision": decision, "checks": checks, "order_id": request.order_id},
            user_message={
                "en": summary,
                "hi": "Return evidence check hua; agla fair step bataya gaya hai.",
            },
        )

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        with SessionLocal() as session:
            log_agent_call(
                session,
                agent_name="return_verifier",
                entity_type="return",
                entity_id=request.order_id,
                confidence=score,
                latency_ms=latency_ms,
                input_ref=request.video_key,
                provider=(
                    f"clip+resnet50+{self.context.reasoner.name}"
                    if not label_error
                    else f"clip+resnet50 ({self.context.reasoner.name} unavailable)"
                ),
                output_json=result.data,
            )
            session.commit()

        return result
