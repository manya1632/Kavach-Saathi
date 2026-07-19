from __future__ import annotations

from unittest.mock import AsyncMock, patch

from conftest import poll_run
from sqlalchemy import select

from kavach_saathi.db.base import SessionLocal
from kavach_saathi.db.models import AgentLog, Product
from kavach_saathi.providers.reasoning import ReasoningUnavailable
from kavach_saathi.providers.spec_ocr import ExtractedSpec

CV_COTTON_MAROON = {
    "clip_fabric": "cotton",
    "clip_confidence": 0.9,
    "resnet_top_labels": [{"label": "jean", "confidence": 0.4}],
    "resnet_fabric_hint": None,
    "dominant_color_hex": "#800000",
}

# No GEMINI_API_KEY/GROQ_API_KEY is configured in the test environment, so the
# container's reasoner is DemoReasoningProvider -- that's the one whose `structured()`
# these tests mock, the same call path SpecEnforcerAgent goes through via
# `self.context.reasoner.structured(...)`.
OCR_TARGET = "kavach_saathi.providers.reasoning.DemoReasoningProvider.structured"
CV_TARGET = "kavach_saathi.providers.spec_vision.FabricVisionClassifier.classify"


_FULL_DECLARED_SPECS = {
    "gsm": 150,
    "fabric": "60% Cotton, 40% Viscose",
    "color_hex": "#800000",
    "wash_care": "Gentle hand wash",
}


def _reset_product_p001():
    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        product.status = "active"
        product.spec_source = "seller_form"
        # Also reset spec_json -- several tests below deliberately trim this down to
        # exercise the missing-field path, and the `client` fixture is session-scoped
        # (one shared DB across the whole test run), so a prior test's mutation would
        # otherwise leak into whichever test runs next.
        product.spec_json = dict(_FULL_DECLARED_SPECS)
        session.commit()


def test_extraction_success_activates_listing_and_logs_real_confidence(client) -> None:
    _reset_product_p001()
    extracted = ExtractedSpec(
        fabric="60% Cotton, 40% Viscose", gsm=150, color_hex="#800000", wash_care="Gentle hand wash",
        label_visible=True,
    )
    with (
        patch(OCR_TARGET, new=AsyncMock(return_value=extracted)),
        patch(CV_TARGET, return_value=CV_COTTON_MAROON),
    ):
        response = client.post("/v1/agents/spec-enforcer/extract", json={"product_id": "P-001"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["missing_fields"] == []
    assert body["mismatches"] == []
    assert body["spec_json"]["fabric"] == "60% Cotton, 40% Viscose"

    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        assert product.status == "active"
        assert product.spec_source == "extracted"

        log = session.execute(
            select(AgentLog)
            .where(AgentLog.agent_name == "spec_enforcer", AgentLog.entity_id == "P-001")
            .order_by(AgentLog.id.desc())
        ).scalars().first()
        assert log.provider == "demo_deterministic+clip+resnet50"
        assert log.confidence > 0


def test_spec_ocr_prefers_uploaded_catalogue_label_images(client) -> None:
    _reset_product_p001()
    label_keys = ["uploads/catalogue/care-front.png", "uploads/catalogue/care-back.png"]
    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        original_keys = list(product.catalogue_images or [])
        product.catalogue_images = label_keys
        session.commit()

    extracted = ExtractedSpec(
        fabric="Cotton", gsm=180, color_hex="#800000", wash_care="Machine wash cold", label_visible=True
    )
    read_mock = AsyncMock(return_value=b"catalogue-label-image")
    try:
        with (
            patch("kavach_saathi.agents.specs.read_image_bytes", new=read_mock),
            patch(OCR_TARGET, new=AsyncMock(return_value=extracted)),
            patch(CV_TARGET, return_value=CV_COTTON_MAROON),
        ):
            response = client.post("/v1/agents/spec-enforcer/extract", json={"product_id": "P-001"})

        assert response.status_code == 200
        assert response.json()["spec_json"]["gsm"] == 180
        assert response.json()["spec_json"]["wash_care"] == "Machine wash cold"
        assert [call.args[0] for call in read_mock.await_args_list] == label_keys
    finally:
        with SessionLocal() as session:
            product = session.get(Product, "P-001")
            product.catalogue_images = original_keys
            session.commit()


def test_ocr_failure_completes_from_already_declared_specs_when_they_agree(client) -> None:
    """OCR found nothing on the label at all, but the product's already-declared specs
    (from a prior seller_form submission) agree with CV -- there's no genuine
    disagreement to resolve, so the listing completes using the declared values rather
    than blocking on a label that simply isn't legible this time."""
    _reset_product_p001()
    extracted = ExtractedSpec(label_visible=False)
    with (
        patch(OCR_TARGET, new=AsyncMock(return_value=extracted)),
        patch(CV_TARGET, return_value=CV_COTTON_MAROON),
    ):
        response = client.post("/v1/agents/spec-enforcer/extract", json={"product_id": "P-001"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["missing_fields"] == []
    assert body["mismatches"] == []

    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        assert product.status == "active"


def test_missing_gsm_and_wash_care_triggers_pending_seller_input(client) -> None:
    """gsm/wash-care instructions have no CV signal to fall back on -- a photo can't
    tell you a fabric's weight or how to launder it -- so if the label doesn't print
    them and the seller never declared them, Agent 2 genuinely can't resolve them and
    asks for seller input. fabric/color, which DO have a CV fallback, still resolve on
    their own even with nothing declared for them either."""
    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        product.status = "active"
        product.spec_source = "seller_form"
        # "applicable" (checked for missing-ness at all) is gated on the *key* being
        # declared, not a truthy value -- gsm/wash_care must still be present as keys
        # (with a null value, i.e. "the seller was asked but didn't have it") for the
        # missing-field path to consider them, distinct from a category where they're
        # simply not tracked at all.
        product.spec_json = {
            "fabric": "60% Cotton, 40% Viscose",
            "color_hex": "#800000",
            "gsm": None,
            "wash_care": None,
        }
        session.commit()

    extracted = ExtractedSpec(label_visible=False)
    with (
        patch(OCR_TARGET, new=AsyncMock(return_value=extracted)),
        patch(CV_TARGET, return_value=CV_COTTON_MAROON),
    ):
        response = client.post("/v1/agents/spec-enforcer/extract", json={"product_id": "P-001"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_evidence"
    assert set(body["missing_fields"]) == {"gsm", "wash_care"}
    assert body["spec_json"]["fabric"] == "60% Cotton, 40% Viscose"
    assert body["spec_json"]["color_hex"] == "#800000"

    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        assert product.status == "pending_seller_input"

    _reset_product_p001()


def test_submit_missing_rejects_when_not_pending(client) -> None:
    _reset_product_p001()  # status=active, not pending_seller_input
    response = client.post(
        "/v1/agents/spec-enforcer/submit-missing", json={"product_id": "P-001", "fields": {"gsm": 150}}
    )
    assert response.status_code == 409


def test_submit_missing_completes_listing_when_cv_agrees(client) -> None:
    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        product.status = "pending_seller_input"
        session.commit()

    extracted = ExtractedSpec(label_visible=False)
    with (
        patch(OCR_TARGET, new=AsyncMock(return_value=extracted)),
        patch(CV_TARGET, return_value=CV_COTTON_MAROON),
    ):
        response = client.post(
            "/v1/agents/spec-enforcer/submit-missing",
            json={
                "product_id": "P-001",
                "fields": {
                    "fabric": "100% Cotton",
                    "gsm": 150,
                    "color_hex": "#800000",
                    "wash_care": "Gentle hand wash",
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"

    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        assert product.status == "active"
        assert product.spec_source == "seller_form"

    _reset_product_p001()


def test_submit_missing_trusts_seller_value_even_if_cv_disagrees(client) -> None:
    """A seller-submitted spec value used to get cross-checked against CLIP's
    zero-shot fabric guess and blocked as a "conflict" whenever they disagreed. That
    was backwards -- a rough zero-shot CV guess isn't ground truth to hold a genuine
    claim to account against -- so it's no longer treated as a conflict; the seller's
    value is trusted directly."""
    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        product.status = "pending_seller_input"
        session.commit()

    extracted = ExtractedSpec(label_visible=False)
    with (
        patch(OCR_TARGET, new=AsyncMock(return_value=extracted)),
        patch(CV_TARGET, return_value=CV_COTTON_MAROON),  # CV says cotton -- no longer a blocker
    ):
        response = client.post(
            "/v1/agents/spec-enforcer/submit-missing",
            json={
                "product_id": "P-001",
                "fields": {
                    "fabric": "100% Polyester",
                    "gsm": 150,
                    "color_hex": "#800000",
                    "wash_care": "Gentle hand wash",
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["mismatches"] == []
    assert body["spec_json"]["fabric"] == "100% Polyester"

    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        assert product.status == "active"

    _reset_product_p001()

    _reset_product_p001()


def test_ocr_unavailable_falls_back_to_seller_specs_honestly(client, mock_catalogue_generation) -> None:
    """When no reasoning provider is configured, the agent must not fabricate a
    successful extraction -- it should honestly report the OCR source as unavailable
    while still functioning off seller-provided fields, cross-checked by CV."""
    _reset_product_p001()
    with (
        patch(OCR_TARGET, new=AsyncMock(side_effect=ReasoningUnavailable("no reasoning provider configured"))),
        patch(CV_TARGET, return_value=CV_COTTON_MAROON),
    ):
        response = client.post(
            "/v1/listings/analyze",
            json={
                "seller_id": "S-001",
                "product_id": "P-001",
                "image_keys": ["assets/mock/products/P-001.png"],
                "seller_specs": {
                    "fabric": "60% Cotton, 40% Viscose",
                    "gsm": 150,
                    "color_hex": "#800000",
                    "wash_care": "Gentle hand wash",
                },
            },
        )
        assert response.status_code == 200
        body = poll_run(client, response.json()["run_id"])

    spec_result = body["results"]["spec_enforcer"]
    assert spec_result["evidence"][0]["source"] == "demo_deterministic_vision_ocr_unavailable"
    assert spec_result["data"]["ocr_error"] is not None
    assert spec_result["status"] == "completed"  # seller_specs + CV agreement still resolves it
