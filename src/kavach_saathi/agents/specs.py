from __future__ import annotations

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
from kavach_saathi.providers.reasoning import ReasoningUnavailable
from kavach_saathi.providers.spec_ocr import EXTRACTION_PROMPT, EXTRACTION_SYSTEM_PROMPT, ExtractedSpec
from kavach_saathi.providers.spec_vision import FabricVisionClassifier, hex_color_distance

IMAGE_VERIFIABLE_FIELDS = ("fabric", "gsm", "color_hex", "wash_care")
_COLOR_MISMATCH_THRESHOLD = 0.35


class SpecEnforcerAgent(Agent):
    """Agent 2: Honest Spec Enforcer (final target plan.md Section 6).

    Reads the catalogue image itself -- the configured multimodal reasoning provider
    (Gemini; the plan names Claude, see project notes for the free-tier substitution)
    extracts any visible label/tag text, CLIP + ResNet-50 independently infer
    fabric/color from the garment photo, and the two are cross-checked. This replaces
    the previous implementation, which compared the seller's form input against a
    value already sitting in the product's fixture record -- a deterministic string
    match with no image reading at all (gap_report B2).
    """

    def __init__(self, context):
        super().__init__(context)
        self.vision = FabricVisionClassifier()

    async def run(self, request: ListingAnalyzeRequest) -> AgentResult:
        started_at = time.perf_counter()
        settings = get_settings()
        product = self.context.repository.get("products", request.product_id)

        images = [await read_image_bytes(key, settings) for key in request.image_keys]

        ocr_error: str | None = None
        try:
            extracted = await self.context.reasoner.structured(
                system=EXTRACTION_SYSTEM_PROMPT,
                prompt=EXTRACTION_PROMPT,
                schema=ExtractedSpec,
                images=images,
            )
        except ReasoningUnavailable as exc:
            ocr_error = str(exc)
            extracted = ExtractedSpec(label_visible=False)

        cv_result = self.vision.classify(images[0])
        ocr_source_label = f"{self.context.reasoner.name}_vision_ocr"

        mismatches: list[dict] = []
        final: dict[str, object] = {}
        sources: dict[str, str] = {}

        # fabric: prefer OCR, cross-check against CLIP; fall back to seller_specs if OCR
        # found nothing, then cross-check the seller-typed value against CLIP too (the
        # plan's "seller types cotton but CV detects polyester" scenario).
        fabric_candidate = extracted.fabric or request.seller_specs.get("fabric")
        fabric_from = ocr_source_label if extracted.fabric else ("seller_form" if fabric_candidate else None)
        if fabric_candidate:
            if cv_result["clip_fabric"].lower() not in fabric_candidate.lower():
                mismatches.append(
                    {
                        "field": "fabric",
                        "claimed": fabric_candidate,
                        "claimed_source": fabric_from,
                        "cv_detected": cv_result["clip_fabric"],
                        "cv_source": "clip_zero_shot",
                    }
                )
            else:
                final["fabric"] = fabric_candidate
                sources["fabric"] = fabric_from

        color_candidate = extracted.color_hex or request.seller_specs.get("color_hex")
        color_from = ocr_source_label if extracted.color_hex else ("seller_form" if color_candidate else None)
        if color_candidate:
            distance = hex_color_distance(color_candidate, cv_result["dominant_color_hex"])
            if distance > _COLOR_MISMATCH_THRESHOLD:
                mismatches.append(
                    {
                        "field": "color_hex",
                        "claimed": color_candidate,
                        "claimed_source": color_from,
                        "cv_detected": cv_result["dominant_color_hex"],
                        "cv_source": "dominant_color_extraction",
                        "distance": round(distance, 3),
                    }
                )
            else:
                final["color_hex"] = color_candidate
                sources["color_hex"] = color_from

        for field in ("gsm", "wash_care"):
            candidate = getattr(extracted, field, None) or request.seller_specs.get(field)
            if candidate:
                final[field] = candidate
                sources[field] = ocr_source_label if getattr(extracted, field, None) else "seller_form"

        # Listings have category-specific, flexible specifications. Agent 2 only asks
        # for a missing value when the seller actually declared that image/label-
        # verifiable field; it never forces garment fields onto unrelated products.
        applicable_fields = [field for field in IMAGE_VERIFIABLE_FIELDS if field in request.seller_specs]
        missing_fields = [field for field in applicable_fields if field not in final]

        if mismatches:
            status = RunStatus.NEEDS_EVIDENCE
            confidence = max(20, 55 - len(mismatches) * 15)
            summary = "Seller-claimed specs conflict with what the catalogue image shows."
            self.context.repository.update_product_specs(product["id"], status="inconsistent")
            actions = [
                AgentAction(
                    type="revise_listing", label="Resolve spec conflicts", payload={"mismatches": mismatches}
                )
            ]
        elif missing_fields:
            status = RunStatus.NEEDS_EVIDENCE
            confidence = max(30, 40 + len(final) * 8)
            summary = (
                "Some required specs aren't visible on the catalogue image; seller input "
                "needed for the missing fields only."
            )
            self.context.repository.update_product_specs(product["id"], status="pending_seller_input")
            actions = [
                AgentAction(
                    type="provide_missing_specs",
                    label="Complete missing spec fields",
                    payload={"missing_fields": missing_fields},
                )
            ]
        else:
            status = RunStatus.COMPLETED
            confidence = min(99, 55 + len(final) * 10 + (10 if extracted.label_visible else 0))
            summary = "Specs extracted from the catalogue image and cross-checked against CV analysis."
            spec_source = "extracted" if all(sources.get(f) == ocr_source_label for f in final) else "seller_form"
            prod_status = "draft" if product.get("status") == "extracting" else "active"
            self.context.repository.update_product_specs(
                product["id"], spec_json=final, spec_source=spec_source, status=prod_status
            )
            actions = [AgentAction(type="approve_specs", label="Listing approved")]

        result = AgentResult(
            agent=AgentName.SPEC_ENFORCER,
            status=status,
            confidence=confidence,
            summary=summary,
            evidence=[
                Evidence(
                    key="vision_extraction",
                    value=extracted.model_dump(),
                    source=ocr_source_label if not ocr_error else f"{ocr_source_label}_unavailable",
                ),
                Evidence(key="cv_cross_check", value=cv_result, source="clip_resnet50"),
                Evidence(key="conflicts", value=mismatches, source="cross_check"),
                Evidence(key="unverified_fields", value=missing_fields, source="evidence_policy"),
            ],
            actions=actions,
            data={
                "extracted_specs": final,
                "spec_sources": sources,
                "conflicts": mismatches,
                "unverified": missing_fields,
                "ocr_error": ocr_error,
            },
            user_message={
                "en": summary,
                "hi": "Catalog photo se specs check ho gaye hain.",
            },
        )

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        from kavach_saathi.db.models import Product
        with SessionLocal() as session:
            db_product = session.get(Product, product["id"])
            if db_product:
                db_product.extraction_results = {
                    "extracted_specs": final,
                    "confidence": confidence,
                    "evidence": {
                        "vision_extraction": extracted.model_dump(),
                        "cv_cross_check": cv_result,
                        "ocr_error": ocr_error,
                        "conflicts": mismatches,
                    }
                }
            log_agent_call(
                session,
                agent_name="spec_enforcer",
                entity_type="product",
                entity_id=product["id"],
                confidence=confidence,
                latency_ms=latency_ms,
                input_ref=",".join(request.image_keys),
                provider=(
                    f"{self.context.reasoner.name}+clip+resnet50"
                    if not ocr_error
                    else f"clip+resnet50 ({self.context.reasoner.name} unavailable)"
                ),
                output_json=result.data,
            )
            session.commit()

        return result

