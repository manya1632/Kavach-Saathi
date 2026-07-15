from __future__ import annotations

import time

from kavach_saathi.agent_logging import log_agent_call
from kavach_saathi.agents.base import Agent
from kavach_saathi.db.base import SessionLocal
from kavach_saathi.models import (
    AgentAction,
    AgentName,
    AgentResult,
    Evidence,
    ListingAnalyzeRequest,
    RunStatus,
)


class CatalogueTruthAgent(Agent):
    async def run(self, request: ListingAnalyzeRequest) -> AgentResult:
        started_at = time.perf_counter()
        product = self.context.repository.get("products", request.product_id)
        ground_truth = product.get("ground_truth", {}).get("catalogue", {})
        analysis = await self.context.media.analyze_images(
            request.image_keys,
            "Assess product visibility, blur, obstruction and suitability for a catalog.",
            ground_truth,
        )
        reverse = await self.context.external.reverse_image_search(
            request.image_keys[0],
            {
                "full_matches": ground_truth.get("full_matches", []),
                "partial_matches": ground_truth.get("partial_matches", []),
                "pages": ground_truth.get("pages", []),
            },
        )
        generated = await self.context.media.generate_catalog_views(request.image_keys, product)
        self.context.repository.save_generated_images(product["id"], generated)

        copied = bool(reverse.get("full_matches"))
        self.context.repository.set_stolen_photo_flag(product["id"], copied)
        quality = float(analysis.get("quality", 0.8))
        confidence = round(min(99, 55 + quality * 40))
        status = RunStatus.MANUAL_REVIEW if copied else RunStatus.COMPLETED
        summary = (
            "Possible copied catalogue image found; seller review required."
            if copied
            else "Product media passed source and catalogue-quality checks."
        )
        actions = (
            [AgentAction(type="review_source_match", label="Review source match", payload=reverse)]
            if copied
            else [AgentAction(type="continue", label="Continue to specification check")]
        )
        providers_used = sorted({image["provider"] for image in generated})

        result = AgentResult(
            agent=AgentName.CATALOGUE_TRUTH,
            status=status,
            confidence=confidence,
            summary=summary,
            evidence=[
                Evidence(key="image_quality", value=quality, source="nova_vision"),
                Evidence(key="web_matches", value=reverse, source="google_vision_web_detection"),
                Evidence(key="generated_views", value=generated, source="/".join(providers_used)),
            ],
            actions=actions,
            data={"generated_views": generated, "source_check": reverse},
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
                provider="/".join(providers_used),
                output_json={
                    "generated_views": generated,
                    "copied": copied,
                    "quality": quality,
                    "web_matches": reverse,
                },
            )
            session.commit()

        return result
