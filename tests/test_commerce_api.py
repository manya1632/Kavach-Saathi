from __future__ import annotations

import uuid
from unittest.mock import patch

from conftest import poll_agent_log


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@pytest.kavachsaathi.test"


def _signup_seller(client) -> str:
    response = client.post(
        "/v1/auth/signup",
        json={
            "role": "seller",
            "name": "Commerce Seller",
            "password": "correct-horse-1",
            "email": _unique_email("commerce-seller"),
            "business_name": "Commerce Seller Co",
        },
    )
    return response.json()["access_token"]


def _signup_buyer(client) -> str:
    response = client.post(
        "/v1/auth/signup",
        json={
            "role": "buyer",
            "name": "Commerce Buyer",
            "password": "correct-horse-1",
            "email": _unique_email("commerce-buyer"),
        },
    )
    return response.json()["access_token"]


def _make_variant(client, seller_token: str) -> str:
    headers = {"Authorization": f"Bearer {seller_token}"}
    product = client.post(
        "/v1/seller/products",
        headers=headers,
        json={
            "title": "Commerce Test Kurta",
            "category": "Kurti, Saree & Lehenga",
            "price": 599,
            "original_price": 999,
            "image_keys": ["assets/mock/products/P-001.png"],
        },
    ).json()
    variant = client.post(
        f"/v1/seller/products/{product['id']}/variants",
        headers=headers,
        json={"size": "M", "stock_qty": 5},
    ).json()
    return variant["id"]


def _verified_address_id(client, buyer_headers: dict) -> str:
    # Matches the frontend's own pattern (Storefront.jsx): buyer_id is supplied in the
    # request body, derived from the authenticated user, not enforced server-side --
    # consistent with every other agent-trigger endpoint (size/recommend, voice/query).
    buyer_id = client.get("/v1/auth/me", headers=buyer_headers).json()["id"]
    response = client.post(
        "/v1/address/verify",
        json={
            "buyer_id": buyer_id,
            "raw_address": "Test lane, near market",
            "postal_pin": "495001",
            "coordinates": {"latitude": 22.0797, "longitude": 82.1409},
        },
        headers=buyer_headers,
    )
    from conftest import poll_run

    body = poll_run(client, response.json()["run_id"])
    return body["results"]["address_guardian"]["data"]["address_id"]


def test_cart_add_update_remove(client) -> None:
    seller_token = _signup_seller(client)
    buyer_token = _signup_buyer(client)
    headers = {"Authorization": f"Bearer {buyer_token}"}
    variant_id = _make_variant(client, seller_token)

    added = client.post("/v1/cart", headers=headers, json={"product_variant_id": variant_id, "qty": 2})
    assert added.status_code == 201
    items = added.json()["items"]
    assert len(items) == 1
    assert items[0]["qty"] == 2
    item_id = items[0]["id"]

    updated = client.patch(f"/v1/cart/{item_id}", headers=headers, json={"qty": 3})
    assert updated.json()["items"][0]["qty"] == 3

    removed = client.delete(f"/v1/cart/{item_id}", headers=headers)
    assert removed.json()["items"] == []


def test_order_creation_cod_decrements_stock_and_clears_cart(client) -> None:
    seller_token = _signup_seller(client)
    buyer_token = _signup_buyer(client)
    headers = {"Authorization": f"Bearer {buyer_token}"}
    variant_id = _make_variant(client, seller_token)

    client.post("/v1/cart", headers=headers, json={"product_variant_id": variant_id, "qty": 2})
    address_id = _verified_address_id(client, headers)

    order = client.post("/v1/orders", headers=headers, json={"address_id": address_id, "payment_mode": "cod"})
    assert order.status_code == 201
    body = order.json()
    assert body["status"] == "PLACED"
    assert body["payment_mode"] == "cod"
    assert body["razorpay"] is None

    cart_after = client.get("/v1/cart", headers=headers).json()
    assert cart_after["items"] == []

    orders = client.get("/v1/orders", headers=headers).json()
    assert any(o["id"] == body["order_id"] for o in orders)


def test_cod_order_publishes_event_and_triggers_agent7(client) -> None:
    """A COD order placed through the real endpoint should publish `order.placed` to
    Redis Streams and have Agent 7 (DeliveryConfirmationAgent) pick it up automatically
    via the background consumer -- no frontend 'simulate' button needed (gap_report
    B1). TWILIO_ACCOUNT_SID/PUBLIC_BASE_URL are cleared in the test environment (see
    conftest.py), so this exercises the real event chain end to end while landing on
    the honest 'not configured' branch rather than placing a real call."""
    seller_token = _signup_seller(client)
    buyer_token = _signup_buyer(client)
    headers = {"Authorization": f"Bearer {buyer_token}"}
    variant_id = _make_variant(client, seller_token)

    client.post("/v1/cart", headers=headers, json={"product_variant_id": variant_id, "qty": 1})
    address_id = _verified_address_id(client, headers)

    order = client.post("/v1/orders", headers=headers, json={"address_id": address_id, "payment_mode": "cod"})
    assert order.status_code == 201
    order_id = order.json()["order_id"]

    log = poll_agent_log("delivery_confirmation", order_id, timeout=15.0)
    # Both "not configured" (TWILIO_ACCOUNT_SID cleared) and "no phone on file" (this
    # test's freshly-signed-up buyer never set one) are honest degrade outcomes here --
    # which one lands depends on read timing versus other honest-degrade checks in
    # initiate_call, not on whether the real event chain fired for real.
    assert log.provider == "twilio_unavailable"
    assert log.output_json["error"] in (
        "Twilio is not configured (TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER)",
        "Buyer has no phone number on file",
    )


def test_order_creation_prepaid_without_razorpay_fails_honestly(client) -> None:
    """RAZORPAY_KEY_ID/SECRET are cleared in the test environment (see conftest.py) --
    a buyer choosing prepaid must get an honest 503, never a silently faked payment."""
    seller_token = _signup_seller(client)
    buyer_token = _signup_buyer(client)
    headers = {"Authorization": f"Bearer {buyer_token}"}
    variant_id = _make_variant(client, seller_token)

    client.post("/v1/cart", headers=headers, json={"product_variant_id": variant_id, "qty": 1})
    address_id = _verified_address_id(client, headers)

    order = client.post("/v1/orders", headers=headers, json={"address_id": address_id, "payment_mode": "prepaid"})
    assert order.status_code == 503

    # The cart must be untouched -- nothing should have been written before the honest failure.
    cart_after = client.get("/v1/cart", headers=headers).json()
    assert len(cart_after["items"]) == 1


def test_order_creation_rejects_insufficient_stock(client) -> None:
    seller_token = _signup_seller(client)
    buyer_token = _signup_buyer(client)
    headers = {"Authorization": f"Bearer {buyer_token}"}
    variant_id = _make_variant(client, seller_token)  # stock_qty=5

    client.post("/v1/cart", headers=headers, json={"product_variant_id": variant_id, "qty": 20})
    address_id = _verified_address_id(client, headers)

    order = client.post("/v1/orders", headers=headers, json={"address_id": address_id, "payment_mode": "cod"})
    assert order.status_code == 409


def test_review_creation_publishes_event_and_triggers_agent4(client) -> None:
    """A review posted through the real endpoint should publish to Redis Streams and
    have Agent 4 (ReviewFilterAgent) pick it up automatically via the background
    consumer -- no manual 'Check review truth' trigger needed (gap_report B4/Y2)."""
    buyer_token = _signup_buyer(client)
    headers = {"Authorization": f"Bearer {buyer_token}"}

    fake_scores = {"clip_image_text_similarity": None, "bert_text_relevance": 0.9}
    with patch(
        "kavach_saathi.providers.review_vision.ReviewRelevanceClassifier.classify",
        return_value=fake_scores,
    ):
        created = client.post(
            "/v1/reviews",
            headers=headers,
            json={"product_id": "P-001", "rating": 5, "text": "Bahut accha product hai."},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["agent4_queued"] is True

        log = poll_agent_log("review_filter", body["id"], timeout=15.0)
    assert log.provider == "clip+bert_multilingual"
    assert log.output_json["relevant"] is True


def test_review_requires_matching_order_ownership(client) -> None:
    buyer_token = _signup_buyer(client)
    headers = {"Authorization": f"Bearer {buyer_token}"}
    response = client.post(
        "/v1/reviews",
        headers=headers,
        json={"product_id": "P-001", "order_id": "O-GOLDEN", "rating": 4, "text": "Not my order"},
    )
    assert response.status_code == 403
