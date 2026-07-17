from __future__ import annotations

import asyncio
import logging
import time

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
    ListingAnalyzeRequest,
    RunStatus,
)
from kavach_saathi.providers.image_quality import ImageQualityAssessor
from kavach_saathi.providers.stolen_photo import GoogleVisionReverseImageSearch, GoogleVisionUnavailable


class CatalogueTruthAgent(Agent):
    """Agent 1: Catalogue Truth Guardian (final target plan.md Section 6). Image
    generation (SAM 2.0 -> Nano Banana 2 -> Stable Diffusion fallback) was already
    real as of Sub-phase 3; this rewrite closes the remaining gap where "image
    quality" and the stolen-photo check still read a `ground_truth` fixture field
    that no longer even exists on the Postgres `products` table (Sub-phase 0 moved
    it to `eval_fixtures`), so both were silently returning constant values
    regardless of the uploaded photo. Bypasses `context.media`/`context.external`
    and instantiates its own providers directly, matching the pattern used by
    Agents 3/5/6/7/8.
    """

    def __init__(self, context):
        super().__init__(context)
        self.quality_assessor = ImageQualityAssessor()
        self.stolen_photo = GoogleVisionReverseImageSearch(get_settings())

    async def run(self, request: ListingAnalyzeRequest) -> AgentResult:
        started_at = time.perf_counter()
        settings = get_settings()
        product = self.context.repository.get("products", request.product_id)

        primary_image = await read_image_bytes(request.image_keys[0], settings)
        quality_result = self.quality_assessor.assess(primary_image)

        reverse_error: str | None = None
        try:
            reverse = await self.stolen_photo.search(primary_image)
        except GoogleVisionUnavailable as exc:
            reverse_error = str(exc)
            reverse = {"full_matches": [], "partial_matches": [], "pages": []}

        # Image generation (SAM 2.0 segmentation + the VTON/fallback provider chain)
        # must never block or fail the whole listing -- a slow/broken provider is an
        # Agent 1-specific problem, not a reason to also lose Agent 2's spec results
        # or leave the seller staring at a dead run. Capped and caught here so a
        # timeout/exception degrades to "using the seller's own photo, pending
        # review" instead of propagating up and failing the entire graph.
        image_gen_error: str | None = None
        try:
            # 4 sequential views, each its own network round-trip through the
            # FASHN/Nano-Banana/Hugging-Face cascade, can genuinely take a bit over
            # 2 minutes on an ordinary run (observed live: 126s against this
            # function's old 120s budget) -- raised to give real, working provider
            # calls enough headroom instead of getting cut off by a few seconds and
            # falling all the way through to "pending admin review".
            generated = await asyncio.wait_for(
                self.context.media.generate_catalog_views(request.image_keys, product), timeout=240
            )
            self.context.repository.save_generated_images(product["id"], generated)
        except Exception as exc:  # noqa: BLE001 - any image-gen failure degrades gracefully, never crashes the run
            # `str(exc)` is empty for some exception types (notably a bare
            # asyncio.TimeoutError from wait_for above) -- falling back to the
            # exception's class name keeps `image_gen_error` truthy whenever an
            # exception genuinely occurred, so the status/summary logic below (which
            # branches on `if image_gen_error`) can't silently mistake "timed out
            # with no message" for "no error, generation actually succeeded" while
            # `generated` is empty.
            image_gen_error = str(exc) or f"{type(exc).__name__} (no error message)"
            logging.getLogger(__name__).warning(
                "Agent 1 image generation failed for product %s: %s", product["id"], image_gen_error, exc_info=True
            )
            generated = []

        # Honest degrade: with no stolen-photo check actually run, this can only ever
        # report "not flagged" (never a false accusation) -- never "match found".
        copied = bool(reverse.get("full_matches")) and not reverse_error
        self.context.repository.set_stolen_photo_flag(product["id"], copied)
        quality = float(quality_result["quality"])
        confidence = round(min(99, 55 + quality * 40))
        status = (
            RunStatus.MANUAL_REVIEW
            if copied
            else RunStatus.RETRYABLE
            if image_gen_error
            else RunStatus.COMPLETED
        )
        summary = (
            "Possible copied catalogue image found; seller review required."
            if copied
            else "Model-wearing photos couldn't be generated right now; showing your uploaded photo until an "
            "admin review completes."
            if image_gen_error
            else "Product media passed source and catalogue-quality checks."
        )
        actions = (
            [AgentAction(type="review_source_match", label="Review source match", payload=reverse)]
            if copied
            else [AgentAction(type="retry_image_generation", label="Image generation pending admin review")]
            if image_gen_error
            else [AgentAction(type="continue", label="Continue to specification check")]
        )
        providers_used = sorted({image["provider"] for image in generated})

        result = AgentResult(
            agent=AgentName.CATALOGUE_TRUTH,
            status=status,
            confidence=confidence,
            summary=summary,
            evidence=[
                Evidence(key="image_quality", value=quality_result, source="opencv_blur_resolution_brightness"),
                Evidence(
                    key="web_matches",
                    value=reverse,
                    source="google_vision_web_detection" if not reverse_error else "unavailable",
                ),
                Evidence(key="reverse_search_error", value=reverse_error, source="fallback_policy"),
                Evidence(
                    key="generated_views",
                    value=generated,
                    source="/".join(providers_used) if providers_used else "pending",
                ),
                Evidence(key="image_generation_error", value=image_gen_error, source="fallback_policy"),
            ],
            actions=actions,
            data={"generated_views": generated, "source_check": reverse, "image_generation_error": image_gen_error},
            user_message={
                "en": summary,
                "hi": "Catalog photo ki quality aur source check ho gaya.",
            },
        )

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        with SessionLocal() as session:
            log_agent_call(
                session,
                agent_name="catalogue_truth",
                entity_type="product",
                entity_id=product["id"],
                confidence=confidence,
                latency_ms=latency_ms,
                input_ref=",".join(request.image_keys),
                provider="/".join(providers_used) if providers_used else "pending",
                output_json={
                    "generated_views": generated,
                    "copied": copied,
                    "quality": quality,
                    "web_matches": reverse,
                },
            )
            session.commit()

        return result
