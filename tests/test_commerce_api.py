from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
    """Address persistence went through a deliberate architecture split (commit
    445ce8e "feat: integrate address guardian and fix spec evidence flow"):
    /v1/address/verify is now pure validation (no persistence, no phone check) --
    the real persisted Address row, whose id /v1/orders needs, only comes from
    /v1/addresses, which additionally carrier-verifies the phone via Twilio Lookup.
    GOOGLE_MAPS_API_KEY/TWILIO_ACCOUNT_SID are both cleared in the test environment
    (conftest.py), so both providers are mocked here for a deterministic pass."""
    fake_geo = {
        "label": "Verified landmark address, Bilaspur, Chhattisgarh 495001",
        "city": "Bilaspur",
        "district": "Bilaspur",
        "state": "Chhattisgarh",
        "postal_pin": "495001",
    }
    fake_lookup = SimpleNamespace(
        valid=True,
        phone_number="+919748572321",
        country_code="IN",
        line_type_intelligence={"carrier_name": "Airtel", "type": "mobile"},
        url="https://lookups.twilio.com/v2/PhoneNumbers/+919748572321",
    )
    phone_numbers = MagicMock()
    phone_numbers.fetch.return_value = fake_lookup
    twilio_client = MagicMock()
    twilio_client.lookups.v2.phone_numbers.return_value = phone_numbers

    with (
        patch(
            "kavach_saathi.providers.google_maps.GoogleMapsGeocoder.reverse_geocode",
            new=AsyncMock(return_value=fake_geo),
        ),
        patch(
            "kavach_saathi.providers.twilio_integration.TwilioIntegrationClient.is_configured",
            new_callable=lambda: property(lambda self: True),
        ),
        patch(
            "kavach_saathi.providers.twilio_integration.TwilioIntegrationClient._client",
            return_value=twilio_client,
        ),
    ):
        response = client.post(
            "/v1/addresses",
            json={
                "recipient_name": "Test Buyer",
                "phone": "9748572321",
                "address_line1": "Test lane, near market",
                "city": "Bilaspur",
                "district": "Bilaspur",
                "state": "Chhattisgarh",
                "postal_pin": "495001",
                "latitude": 22.0797,
                "longitude": 82.1409,
            },
            headers=buyer_headers,
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


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
    # AWAITING_BUYER_CONFIRMATION is the real initial status now -- the WhatsApp
    # confirmation flow (order_status.py's state machine) inserted a confirmation step
    # before an order is considered CONFIRMED; the "PLACED" status doesn't exist.
    assert body["status"] == "AWAITING_BUYER_CONFIRMATION"
    assert body["payment_mode"] == "cod"
    assert body["razorpay"] is None

    cart_after = client.get("/v1/cart", headers=headers).json()
    assert cart_after["items"] == []

    orders = client.get("/v1/orders", headers=headers).json()
    assert any(o["id"] == body["order_id"] for o in orders)


def test_cod_order_publishes_event_and_triggers_agent7(client) -> None:
    """A COD order placed through the real endpoint should publish `order.placed` to
    Redis Streams and have the order-event consumer (events.py's
    _trigger_delivery_confirmation_call) pick it up automatically to send the
    WhatsApp ownership-confirmation prompt -- no frontend 'simulate' button needed
    (gap_report B1). That consumer doesn't write to agent_logs at all (unlike
    DeliveryConfirmationAgent.initiate_call, a separate later step in the flow); it's
    a bare Twilio WhatsApp content-template send, so the event chain is verified here
    by mocking TwilioIntegrationClient.send_whatsapp_content and polling the order's
    whatsapp_workflow_state for the transition the consumer makes on success."""
    import time as _time

    from kavach_saathi.db.base import SessionLocal
    from kavach_saathi.db.models import Order

    seller_token = _signup_seller(client)
    buyer_token = _signup_buyer(client)
    headers = {"Authorization": f"Bearer {buyer_token}"}
    variant_id = _make_variant(client, seller_token)

    client.post("/v1/cart", headers=headers, json={"product_variant_id": variant_id, "qty": 1})
    address_id = _verified_address_id(client, headers)

    with patch(
        "kavach_saathi.providers.twilio_integration.TwilioIntegrationClient.send_whatsapp_content",
        return_value="SMxxxx",
    ) as send_mock:
        order = client.post("/v1/orders", headers=headers, json={"address_id": address_id, "payment_mode": "cod"})
        assert order.status_code == 201
        order_id = order.json()["order_id"]

        deadline = _time.monotonic() + 15.0
        state = None
        while _time.monotonic() < deadline:
            with SessionLocal() as session:
                state = session.get(Order, order_id).whatsapp_workflow_state
            if state == "ownership_prompt_sent":
                break
            _time.sleep(0.1)

    assert state == "ownership_prompt_sent"
    calls_for_this_order = [call for call in send_mock.call_args_list if call.args[2] == {"1": order_id}]
    assert len(calls_for_this_order) == 1


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
    """/v1/cart already rejects a qty over stock_qty at add-to-cart time, so the only
    way order creation's own stock check can actually fire is a depletion that
    happens after the item is already in the cart (another buyer's order, restock
    correction, etc.) -- simulated directly here to exercise that real race-condition
    guard rather than the earlier, already-covered cart-add check."""
    from kavach_saathi.db.base import SessionLocal
    from kavach_saathi.db.models import ProductVariant

    seller_token = _signup_seller(client)
    buyer_token = _signup_buyer(client)
    headers = {"Authorization": f"Bearer {buyer_token}"}
    variant_id = _make_variant(client, seller_token)  # stock_qty=5

    client.post("/v1/cart", headers=headers, json={"product_variant_id": variant_id, "qty": 3})
    address_id = _verified_address_id(client, headers)

    with SessionLocal() as session:
        variant = session.get(ProductVariant, variant_id)
        variant.stock_qty = 1
        session.commit()

    order = client.post("/v1/orders", headers=headers, json={"address_id": address_id, "payment_mode": "cod"})
    assert order.status_code == 409


def _delivered_order_for_review(buyer_id: str) -> str:
    # ReviewCreateRequest now requires order_id -- a review can only be attached to a
    # delivered order that actually contains the product (models.py added this along
    # with the reviews.order_id NOT NULL FK). Direct DB insert matches the established
    # pattern for this in test_characterization.py/test_saathi_features.py rather than
    # driving the full cart -> order -> delivery-confirmation lifecycle just for this.
    from kavach_saathi.db.base import SessionLocal
    from kavach_saathi.db.models import Order, OrderItem
    from kavach_saathi.order_status import OrderStatus

    order_id = f"O-REVIEW-{uuid.uuid4().hex[:10].upper()}"
    with SessionLocal() as session:
        order = Order(
            id=order_id, buyer_id=buyer_id, status=OrderStatus.DELIVERED, total_amount=599.0, payment_mode="cod"
        )
        item = OrderItem(
            order_id=order_id,
            product_id="P-001",
            product_variant_id=None,
            seller_id="S-001",
            size="M",
            qty=1,
            price_at_purchase=599.0,
        )
        session.add(order)
        session.add(item)
        session.commit()
    return order_id


def test_review_creation_publishes_event_and_triggers_agent4(client) -> None:
    """A review posted through the real endpoint should publish to Redis Streams and
    have Agent 4 (ReviewFilterAgent) pick it up automatically via the background
    consumer -- no manual 'Check review truth' trigger needed (gap_report B4/Y2)."""
    buyer_token = _signup_buyer(client)
    headers = {"Authorization": f"Bearer {buyer_token}"}
    buyer_id = client.get("/v1/auth/me", headers=headers).json()["id"]
    order_id = _delivered_order_for_review(buyer_id)

    # ReviewVerificationProvider.verify (a synchronous Gemini/Groq LLM check inside
    # create_review, ahead of the async agent4/review_vision path below) needs
    # GEMINI_API_KEY/GROQ_API_KEY -- both cleared in the test environment -- so it's
    # mocked directly here to reach the "review saved" path this test is actually about.
    from kavach_saathi.providers.review_provider import ReviewVerificationResult

    fake_verification = ReviewVerificationResult(
        product_image_match_passed=True,
        product_image_match_confidence=90,
        product_image_match_reason="Matches catalogue image.",
        image_text_match_passed=True,
        image_text_match_confidence=90,
        image_text_match_reason="Text matches the photo.",
        text_quality_passed=True,
        text_quality_classification="genuine",
        text_quality_reason="Specific, on-topic feedback.",
        overall_passed=True,
        provider="test_mock",
        model="test_mock",
    )

    fake_scores = {"clip_image_text_similarity": None, "bert_text_relevance": 0.9}
    with (
        patch(
            "kavach_saathi.providers.review_vision.ReviewRelevanceClassifier.classify",
            return_value=fake_scores,
        ),
        patch(
            "kavach_saathi.providers.review_provider.ReviewVerificationProvider.verify",
            new=AsyncMock(return_value=fake_verification),
        ),
    ):
        created = client.post(
            "/v1/reviews",
            headers=headers,
            json={
                "product_id": "P-001",
                "order_id": order_id,
                "rating": 5,
                "text": "Bahut accha product hai.",
                "image_key": "assets/mock/products/P-001.png",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["agent4_queued"] is True

        log = poll_agent_log("review_filter", body["id"], timeout=15.0)
    assert log.provider == "clip+bert_multilingual"
    assert log.output_json["relevant"] is True


def test_review_requires_matching_order_ownership(client) -> None:
    """O-GOLDEN belongs to the seeded golden buyer, not this freshly-signed-up one --
    the endpoint folds "wrong order" and "not purchased/delivered" into a single
    honest 400 rather than a separate ownership-specific status (commerce_api.py's
    create_review has no 403 path at all; it never distinguishes *why* the order
    doesn't qualify, only that it doesn't)."""
    buyer_token = _signup_buyer(client)
    headers = {"Authorization": f"Bearer {buyer_token}"}
    response = client.post(
        "/v1/reviews",
        headers=headers,
        json={
            "product_id": "P-001",
            "order_id": "O-GOLDEN",
            "rating": 4,
            "text": "Not my order",
            "image_key": "assets/mock/products/P-001.png",
        },
    )
    assert response.status_code == 400
