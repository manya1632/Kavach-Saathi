from __future__ import annotations

from conftest import poll_run


def test_frontend_is_served(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Run all 8 agents" in response.text
    assert "Ask GPT-OSS" in response.text


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


def test_storefront_demo_context_connects_golden_order(client) -> None:
    body = client.get("/v1/storefront/demo-context").json()
    assert body["buyer"]["id"] == "B-001"
    assert body["order"]["id"] == "O-GOLDEN"
    assert body["order"]["product_id"] == "P-001"


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
    assert result["data"]["address_id"]
    assert any(evidence["key"] == "geocode_error" and evidence["value"] for evidence in result["evidence"])


def test_confirmation_address_update_loops_to_guardian(client) -> None:
    response = client.post(
        "/v1/orders/O-GOLDEN/confirm-simulated",
        json={
            "decision": "update_address",
            "updated_address": {
                "buyer_id": "B-001",
                "raw_address": "Hanuman Mandir ke peeche",
                "postal_pin": "495001",
                "coordinates": {"latitude": 22.0797, "longitude": 82.1409},
            },
        },
    )
    assert set(response.json()["results"]) == {
        "delivery_confirmation",
        "address_guardian",
    }


def test_return_threshold_paths(client) -> None:
    """Agent 8 no longer reads the evidence/expected_confidence fixture-cheat fields
    (gap_report Y9) -- CLIP/ResNet similarity is mocked here to drive each threshold
    deterministically; the real, unmocked pipeline is verified separately (see
    RUNBOOK.md)."""
    from unittest.mock import patch

    best_match_target = "kavach_saathi.providers.return_vision.ReturnVisionVerifier.best_match"
    extract_frames_target = "kavach_saathi.providers.return_vision.ReturnVisionVerifier.extract_frames"
    reasoner_target = "kavach_saathi.providers.reasoning.DemoReasoningProvider.structured"

    from kavach_saathi.providers.spec_ocr import ExtractedSpec

    cases = (
        ("O-GOLDEN", 0.95, True, "completed", "approve"),
        ("O-002", 0.55, False, "needs_evidence", "request_more_evidence"),
        ("O-003", 0.10, False, "manual_review", "manual_inspection"),
    )
    for order_id, clip_score, label_visible, status, decision in cases:
        extracted = ExtractedSpec(fabric=None, label_visible=label_visible)
        with (
            patch(extract_frames_target, return_value=[b"fake-frame-bytes"]),
            patch(best_match_target, return_value=(clip_score, b"fake-frame-bytes")),
            patch(reasoner_target, return_value=extracted),
        ):
            response = client.post(
                "/v1/returns/analyze",
                json={"order_id": order_id, "video_key": "assets/mock/returns/return-approve.mp4"},
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
