from __future__ import annotations

from conftest import poll_run


def test_frontend_is_served(client) -> None:
    """The backend used to serve an inline single-page demo directly at "/" (the "Run
    all 8 agents" / "Ask GPT-OSS" static page); that was replaced by a pure-API
    backend plus a separate Next.js frontend (web/), with "/" now just redirecting
    buyers to FRONTEND_ORIGIN instead of rendering anything itself."""
    from kavach_saathi.config import get_settings

    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == get_settings().frontend_origin


def test_health_reports_all_seed_collections(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["agents"] == 8
    assert body["checks"]["reasoning"] == "deterministic"
    assert body["checks"]["products"] >= 500
    # Reviews are now genuinely writable via POST /v1/reviews (Sub-phase 6), so the
    # count can grow beyond the seeded baseline -- same reasoning as products above.
    assert body["checks"]["reviews"] >= 1000


def test_storefront_catalogue_uses_seed_products(client) -> None:
    response = client.get("/v1/storefront/products", params={"q": "Maroon"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "P-001"
    assert body["items"][0]["seller"]["verified"] is True
    assert body["items"][0]["image_url"].startswith("/mock-assets/")
    assert body["items"][0]["description"]
    assert body["items"][0]["presentation"]["why_it_wins"]


def test_storefront_postgres_search_supports_product_codes_and_typos(client) -> None:
    by_code = client.get("/v1/storefront/products", params={"q": "P-001"})
    assert by_code.status_code == 200
    assert any(item["id"] == "P-001" for item in by_code.json()["items"])

    fuzzy = client.get("/v1/storefront/products", params={"q": "Maron"})
    assert fuzzy.status_code == 200
    assert any("Maroon" in item["name"] for item in fuzzy.json()["items"])


def test_storefront_exposes_all_500_products_in_presentation_order(client) -> None:
    body = client.get("/v1/storefront/products").json()
    # >= not == : the seller portal (Sub-phase 2) lets real sellers add listings beyond
    # the 500 seeded products; the endpoint's default page size caps `items` at 500.
    assert body["total"] >= 500
    assert len(body["items"]) == 500
    assert body["categories"] == [
        "Popular",
        "Kurti, Saree & Lehenga",
        "Women Western",
        "Lingerie",
        "Men",
        "Kids & Toys",
        "Home & Kitchen",
        "Beauty & Health",
        "Jewellery & Accessories",
        "Bags & Footwear",
    ]


# GET /v1/storefront/demo-context was deliberately removed (commit 3651bdc "feat:
# add buyer and return agents") once real JWT-authenticated buyer sessions replaced
# the old hardcoded-golden-buyer (B-001) demo shortcuts -- there's no equivalent
# route left to test in its place.


def test_listing_fans_out_to_two_agents(client, mock_catalogue_generation, mock_spec_vision) -> None:
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
    queued = response.json()
    assert queued["status"] == "queued"  # listing is now a real async workflow (Agent 1 calls real models)
    body = poll_run(client, queued["run_id"])
    assert body["status"] == "completed"
    assert set(body["results"]) == {"catalogue_truth", "spec_enforcer"}


def test_listing_trusts_seller_declared_fabric_even_if_cv_disagrees(
    client, mock_catalogue_generation, mock_spec_vision
) -> None:
    """A seller-declared fabric used to get cross-checked against CLIP's zero-shot
    guess and blocked as a "conflict" whenever they disagreed (mock_spec_vision's CV
    result says "cotton"; this declares "Pure silk") -- that was backwards, since a
    rough zero-shot CV guess isn't ground truth to hold a genuine claim to account
    against. It's no longer treated as a conflict; the declared value is trusted."""
    response = client.post(
        "/v1/listings/analyze",
        json={
            "seller_id": "S-001",
            "product_id": "P-001",
            "image_keys": ["assets/mock/products/P-001.png"],
            "seller_specs": {
                "fabric": "Pure silk",
                "gsm": 150,
                "color_hex": "#800000",
                "wash_care": "Gentle hand wash",
            },
        },
    )
    body = poll_run(client, response.json()["run_id"])
    assert body["status"] == "completed"
    assert body["results"]["spec_enforcer"]["data"]["conflicts"] == []
    assert body["results"]["spec_enforcer"]["data"]["extracted_specs"]["fabric"] == "Pure silk"


def test_voice_size_query_routes_through_two_agents(client) -> None:
    response = client.post(
        "/v1/voice/query",
        json={
            "buyer_id": "B-001",
            "product_id": "P-001",
            "text": "Mujhe kaunsa size lena chahiye?",
            "language": "hi",
            "synthesize_audio": True,
        },
    )
    body = response.json()
    assert set(body["results"]) == {"size_translator", "voice_qa"}
    assert body["results"]["size_translator"]["data"]["recommended_size"] == "XL"
    assert body["results"]["voice_qa"]["data"]["audio_key"].endswith("demo-hi.wav")


def test_irrelevant_review_hides_only_media(client) -> None:
    """Agent 4 no longer reads the expected_relevant/similarity_score fixture-cheat
    fields (gap_report B4) -- CLIP/BERT scores are mocked here to drive a deterministic
    outcome; the real, unmocked pipeline is verified separately (see RUNBOOK.md)."""
    from unittest.mock import patch

    fake_scores = {"clip_image_text_similarity": 0.05, "bert_text_relevance": 0.8}
    with patch(
        "kavach_saathi.providers.review_vision.ReviewRelevanceClassifier.classify",
        return_value=fake_scores,
    ):
        response = client.post(
            "/v1/reviews/analyze",
            json={
                "review_id": "RV-BAD",
                "product_id": "P-001",
                "image_key": "assets/mock/reviews/RV-BAD.png",
            },
        )
        body = poll_run(client, response.json()["run_id"])
    result = body["results"]["review_filter"]
    assert result["data"] == {"relevant": False, "retain_text": True, "scores": fake_scores}
    assert result["actions"][0]["type"] == "hide_media"


def test_relevant_review_keeps_media(client) -> None:
    from unittest.mock import patch

    fake_scores = {"clip_image_text_similarity": 0.31, "bert_text_relevance": 0.72}
    with patch(
        "kavach_saathi.providers.review_vision.ReviewRelevanceClassifier.classify",
        return_value=fake_scores,
    ):
        response = client.post(
            "/v1/reviews/analyze",
            json={
                "review_id": "RV-GOOD",
                "product_id": "P-001",
                "image_key": "assets/mock/reviews/RV-GOOD.png",
            },
        )
        body = poll_run(client, response.json()["run_id"])
    result = body["results"]["review_filter"]
    assert result["data"]["relevant"] is True
    assert result["actions"][0]["type"] == "show_media"


def test_text_only_review_skips_clip(client) -> None:
    """No photo -- Agent 4 should still run BERT text relevance and not fail on a
    missing image_key (it's optional now that reviews can be text-only)."""
    from unittest.mock import patch

    fake_scores = {"clip_image_text_similarity": None, "bert_text_relevance": 0.6}
    with patch(
        "kavach_saathi.providers.review_vision.ReviewRelevanceClassifier.classify",
        return_value=fake_scores,
    ):
        response = client.post(
            "/v1/reviews/analyze",
            json={"review_id": "RV-GOOD", "product_id": "P-001"},
        )
        body = poll_run(client, response.json()["run_id"])
    result = body["results"]["review_filter"]
    assert result["data"]["relevant"] is True
    assert result["data"]["retain_text"] is True


def test_address_verification_and_digipin(client) -> None:
    """GOOGLE_MAPS_API_KEY is cleared for the whole suite (conftest.py) so Agent 6's
    real Google Maps call is mocked here for a deterministic pin match; the
    honest-degrade "geocoder unavailable" path is covered separately below."""
    from unittest.mock import AsyncMock, patch

    fake_geo = {
        "label": "Verified landmark address, Bilaspur, Chhattisgarh 495001",
        "city": "Bilaspur",
        "state": "Chhattisgarh",
        "postal_pin": "495001",
    }
    with patch(
        "kavach_saathi.providers.google_maps.GoogleMapsGeocoder.reverse_geocode",
        new=AsyncMock(return_value=fake_geo),
    ):
        response = client.post(
            "/v1/address/verify",
            json={
                "buyer_id": "B-001",
                "raw_address": "Hanuman Mandir ke peeche, gali no. 3",
                "postal_pin": "495001",
                "coordinates": {"latitude": 22.0797, "longitude": 82.1409},
            },
        )
    result = response.json()["results"]["address_guardian"]
    assert response.json()["status"] == "completed"
    assert len(result["data"]["digipin"]) == 10


def test_address_verification_degrades_honestly_without_geocoder(client) -> None:
    """No GOOGLE_MAPS_API_KEY configured (the default test env) -- Agent 6 must not
    silently claim the postal PIN matches; it should surface the gap and ask for
    manual confirmation instead (gap_report "never fake a match" rule)."""
    response = client.post(
        "/v1/address/verify",
        json={
            "buyer_id": "B-001",
            "raw_address": "Hanuman Mandir ke peeche, gali no. 3",
            "postal_pin": "495001",
            "coordinates": {"latitude": 22.0797, "longitude": 82.1409},
        },
    )
    body = response.json()
    result = body["results"]["address_guardian"]
    assert body["status"] == "needs_evidence"
    # address_id is no longer part of this agent's output -- /v1/address/verify is
    # pure validation now (see _verified_address_id in test_commerce_api.py); the
    # real persisted Address row comes only from the separate, phone-verified
    # POST /v1/addresses.
    assert any(evidence["key"] == "geocode_error" and evidence["value"] for evidence in result["evidence"])


# POST /v1/orders/{id}/confirm-simulated was deliberately removed (commit 3651bdc
# "feat: add buyer and return agents") once the real WhatsApp-based confirmation flow
# replaced this checkout-flow demo shortcut -- there's no equivalent route left to
# test in its place.


def test_return_threshold_paths(client) -> None:
    """Agent 8 no longer reads the evidence/expected_confidence fixture-cheat fields
    (gap_report Y9) -- CLIP/ResNet similarity is mocked here to drive each threshold
    deterministically; the real, unmocked pipeline is verified separately (see
    RUNBOOK.md)."""
    from unittest.mock import patch

    best_match_target = "kavach_saathi.providers.return_vision.ReturnVisionVerifier.best_match"
    extract_frames_target = "kavach_saathi.providers.return_vision.ReturnVisionVerifier.extract_frames"
    reasoner_target = "kavach_saathi.providers.reasoning.DemoReasoningProvider.structured"

    # /v1/returns/analyze writes a real ReturnRecord and stamps the order's status
    # (repository.py's record_return_decision) -- using the shared O-GOLDEN fixture
    # for the "approve" case used to mutate it (status -> RETURN_APPROVED), breaking
    # other tests that assume O-GOLDEN stays "delivered" with its single seeded
    # RT-GOLDEN return. A dedicated, isolated delivered order avoids that.
    import uuid

    from kavach_saathi.db.base import SessionLocal
    from kavach_saathi.db.models import Order, OrderItem
    from kavach_saathi.order_status import OrderStatus
    from kavach_saathi.providers.spec_ocr import ExtractedSpec

    approve_order_id = f"O-RETTEST-{uuid.uuid4().hex[:10].upper()}"
    with SessionLocal() as session:
        session.add(
            Order(
                id=approve_order_id, buyer_id="B-001", status=OrderStatus.DELIVERED,
                total_amount=349.0, payment_mode="cod",
            )
        )
        session.add(
            OrderItem(
                order_id=approve_order_id, product_id="P-001", product_variant_id=None,
                seller_id="S-001", size="M", qty=1, price_at_purchase=349.0,
            )
        )
        session.commit()

    # ReturnAnalyzeRequest now also requires product_id (models.py) -- matching each
    # order's seeded product (data/seed/orders.json) rather than assuming P-001 for all.
    cases = (
        (approve_order_id, "P-001", 0.95, True, "completed", "approve"),
        ("O-002", "P-011", 0.55, False, "needs_evidence", "request_more_evidence"),
        ("O-003", "P-021", 0.10, False, "manual_review", "manual_inspection"),
    )
    for order_id, product_id, clip_score, label_visible, status, decision in cases:
        extracted = ExtractedSpec(fabric=None, label_visible=label_visible)
        with (
            patch(extract_frames_target, return_value=[b"fake-frame-bytes"]),
            patch(best_match_target, return_value=(clip_score, b"fake-frame-bytes")),
            patch(reasoner_target, return_value=extracted),
        ):
            response = client.post(
                "/v1/returns/analyze",
                json={
                    "order_id": order_id,
                    "product_id": product_id,
                    "video_key": "assets/mock/returns/return-approve.mp4",
                },
            )
            body = poll_run(client, response.json()["run_id"])
        assert body["status"] == status, f"{order_id}: {body}"
        assert body["results"]["return_verifier"]["data"]["decision"] == decision


def test_idempotency_reuses_run(client) -> None:
    payload = {
        "buyer_id": "B-001",
        "product_id": "P-001",
        "idempotency_key": "pytest-size-idempotency",
    }
    first = client.post("/v1/size/recommend", json=payload).json()
    second = client.post("/v1/size/recommend", json=payload).json()
    assert first["run_id"] == second["run_id"]


def test_trace_endpoint_emits_sse(client) -> None:
    run = client.post("/v1/size/recommend", json={"buyer_id": "B-001", "product_id": "P-001"}).json()
    response = client.get(f"/v1/runs/{run['run_id']}/events")
    assert response.status_code == 200
    assert "event: workflow_started" in response.text
    assert "event: workflow_completed" in response.text
