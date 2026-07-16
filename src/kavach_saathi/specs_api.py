from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from kavach_saathi.container import Container, get_container
from kavach_saathi.models import ListingAnalyzeRequest

router = APIRouter()


class SpecExtractRequest(BaseModel):
    product_id: str


class SpecSubmitMissingRequest(BaseModel):
    product_id: str
    fields: dict[str, Any]


@router.post("/agents/spec-enforcer/extract")
async def spec_extract(payload: SpecExtractRequest, container: Container = Depends(get_container)):
    """Plan-literal endpoint (final target plan.md Section 6, Agent 2) -- runs the same
    Claude OCR + CLIP/ResNet-50 pipeline as the `/listings/analyze` fan-out, addressable
    on its own so a judge (or the seller portal) can call it directly per the spec."""
    product = container.repository.get("products", payload.product_id)
    image_key = product["media"]["primary"]
    request = ListingAnalyzeRequest(
        seller_id=product["seller_id"],
        product_id=payload.product_id,
        image_keys=[image_key],
        # The seller's originally-declared values (product.spec_json, exposed here as
        # product["specs"]) -- without this, seller_specs was always {}, so Agent 2's
        # "applicable_fields = fields the seller actually declared" check always came
        # back empty and the needs_evidence/pending_seller_input path could never fire,
        # no matter what the listing actually looked like.
        seller_specs=product["specs"] or {},
    )
    result = await container.service.graphs.specs.run(request)
    return {
        "status": result.status,
        "spec_json": result.data["extracted_specs"],
        "missing_fields": result.data["unverified"],
        "mismatches": result.data["conflicts"],
    }


@router.post("/agents/spec-enforcer/submit-missing")
async def spec_submit_missing(payload: SpecSubmitMissingRequest, container: Container = Depends(get_container)):
    """Plan-literal endpoint: the seller submits ONLY the fields Agent 2 couldn't read
    off the image, and Agent 2 re-runs its CV cross-check against the completed spec
    before finalizing or blocking with a diff (final target plan.md Section 6, Agent 2
    step 6). This is the dynamic missing-field re-submission path gap_report B2 flagged
    as entirely absent."""
    product = container.repository.get("products", payload.product_id)
    if product["status"] != "pending_seller_input":
        raise HTTPException(status_code=409, detail="This product is not awaiting missing spec fields")
    image_key = product["media"]["primary"]
    request = ListingAnalyzeRequest(
        seller_id=product["seller_id"],
        product_id=payload.product_id,
        image_keys=[image_key],
        seller_specs=payload.fields,
    )
    result = await container.service.graphs.specs.run(request)
    return {
        "status": result.status,
        "spec_json": result.data["extracted_specs"],
        "missing_fields": result.data["unverified"],
        "mismatches": result.data["conflicts"],
    }
