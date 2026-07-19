from __future__ import annotations

import uuid
from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

from kavach_saathi.config import get_settings
from kavach_saathi.providers import otp_core
from kavach_saathi.providers.email_integration import EmailIntegrationClient
from kavach_saathi.redis_client import get_redis

SEND_OTP_TARGET = "kavach_saathi.providers.email_integration.smtplib.SMTP"


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@pytest.kavachsaathi.test"


@contextmanager
def _email_configured():
    settings = get_settings()
    with ExitStack() as stack:
        stack.enter_context(patch.object(settings, "smtp_host", "smtp.example.test"))
        stack.enter_context(patch.object(settings, "smtp_username", "bot@example.test"))
        stack.enter_context(patch.object(settings, "smtp_password", "app-password"))
        yield


# --- otp_core: channel-agnostic store/verify -------------------------------


def test_store_and_verify_otp_roundtrip():
    settings = get_settings()
    redis = get_redis()
    with patch("kavach_saathi.providers.otp_core.secrets.randbelow", return_value=23456):
        code = otp_core.store_otp(
            redis, settings, purpose="pytest_purpose", reference_id="REF-ROUNDTRIP", contact="someone@example.test"
        )
    assert code == "123456"
    kwargs = {"purpose": "pytest_purpose", "reference_id": "REF-ROUNDTRIP"}
    # Wrong code doesn't consume the stored OTP.
    assert not otp_core.verify_otp(redis, settings, code="000000", **kwargs)
    assert otp_core.verify_otp(redis, settings, code="123456", **kwargs)
    # A verified code is consumed -- can't be replayed.
    assert not otp_core.verify_otp(redis, settings, code="123456", **kwargs)


def test_verify_otp_scoped_to_purpose_and_reference_id():
    """A code stored for one (purpose, reference_id) must not verify against a
    different one, even with the same contact -- this is what keeps a delivery
    OTP from also confirming an unrelated return, for example."""
    settings = get_settings()
    redis = get_redis()
    with patch("kavach_saathi.providers.otp_core.secrets.randbelow", return_value=23456):
        code = otp_core.store_otp(
            redis, settings, purpose="delivery", reference_id="O-TAMPER-TEST", contact="buyer@example.test"
        )
    assert not otp_core.verify_otp(redis, settings, purpose="return", reference_id="O-TAMPER-TEST", code=code)
    assert not otp_core.verify_otp(redis, settings, purpose="delivery", reference_id="OTHER-ORDER", code=code)
    assert otp_core.verify_otp(redis, settings, purpose="delivery", reference_id="O-TAMPER-TEST", code=code)


def test_verify_otp_rejects_after_five_wrong_attempts():
    settings = get_settings()
    redis = get_redis()
    with patch("kavach_saathi.providers.otp_core.secrets.randbelow", return_value=23456):
        code = otp_core.store_otp(
            redis, settings, purpose="pytest_purpose", reference_id="REF-LOCKOUT", contact="someone@example.test"
        )
    kwargs = {"purpose": "pytest_purpose", "reference_id": "REF-LOCKOUT"}
    for _ in range(5):
        assert not otp_core.verify_otp(redis, settings, code="000000", **kwargs)
    # Even the correct code is now rejected -- attempts are exhausted.
    assert not otp_core.verify_otp(redis, settings, code=code, **kwargs)


def test_verify_otp_expires():
    settings = get_settings()
    redis = get_redis()
    with patch("kavach_saathi.providers.otp_core.secrets.randbelow", return_value=23456):
        code = otp_core.store_otp(
            redis, settings, purpose="pytest_purpose", reference_id="REF-EXPIRY", contact="someone@example.test"
        )
    redis.delete(otp_core.otp_key("pytest_purpose", "REF-EXPIRY"))  # simulate TTL expiry
    assert not otp_core.verify_otp(redis, settings, purpose="pytest_purpose", reference_id="REF-EXPIRY", code=code)


# --- EmailIntegrationClient --------------------------------------------------


def test_email_client_unconfigured_raises_honestly():
    settings = get_settings()
    with patch.object(settings, "smtp_host", None):
        client = EmailIntegrationClient(settings)
        try:
            client.send_otp_email("someone@example.test", purpose="signup", reference_id="U-TEST")
            raise AssertionError("expected RuntimeError")
        except RuntimeError:
            pass


def test_email_client_sends_via_smtp_when_configured():
    smtp_instance = MagicMock()
    with (
        _email_configured(),
        patch("kavach_saathi.providers.otp_core.secrets.randbelow", return_value=23456),
        patch(SEND_OTP_TARGET) as smtp_cls,
    ):
        smtp_cls.return_value.__enter__.return_value = smtp_instance
        EmailIntegrationClient(get_settings()).send_otp_email(
            "buyer@example.test", purpose="signup", reference_id="U-SMTP"
        )

    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once()
    smtp_instance.send_message.assert_called_once()
    sent_message = smtp_instance.send_message.call_args[0][0]
    assert sent_message["To"] == "buyer@example.test"

    # The code that was actually emailed verifies through the shared store.
    assert otp_core.verify_otp(get_redis(), get_settings(), purpose="signup", reference_id="U-SMTP", code="123456")


# --- Signup email verification (end to end) ---------------------------------


def test_signup_sends_email_otp_and_verify_activates_account(client) -> None:
    smtp_instance = MagicMock()
    email = _unique_email("signup-otp")
    with (
        _email_configured(),
        patch("kavach_saathi.providers.otp_core.secrets.randbelow", return_value=23456),
        patch(SEND_OTP_TARGET) as smtp_cls,
    ):
        smtp_cls.return_value.__enter__.return_value = smtp_instance
        response = client.post(
            "/v1/auth/signup",
            json={"role": "buyer", "name": "Email OTP Buyer", "password": "correct-horse-1", "email": email},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["email_verification_sent"] is True
    assert body["user"]["email_verified"] is False
    smtp_instance.send_message.assert_called_once()

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    wrong = client.post("/v1/auth/verify-email", headers=headers, json={"otp": "000000"})
    assert wrong.status_code == 400

    right = client.post("/v1/auth/verify-email", headers=headers, json={"otp": "123456"})
    assert right.status_code == 200
    assert right.json()["email_verified"] is True

    me = client.get("/v1/auth/me", headers=headers)
    assert me.json()["email_verified"] is True


def test_signup_without_email_does_not_attempt_verification(client) -> None:
    response = client.post(
        "/v1/auth/signup",
        json={
            "role": "buyer",
            "name": "Phone Only Buyer",
            "password": "correct-horse-1",
            "phone": f"+9199{uuid.uuid4().int % 10**8:08d}",
        },
    )
    assert response.status_code == 201
    assert response.json()["email_verification_sent"] is False


def test_signup_whatsapp_selection_sends_only_whatsapp_and_verifies_phone(client) -> None:
    phone = f"+9198{uuid.uuid4().int % 10**8:08d}"

    def fake_whatsapp_otp(contact: str, *, purpose: str, reference_id: str) -> str:
        assert contact == phone
        assert purpose == "signup"
        with patch("kavach_saathi.providers.otp_core.secrets.randbelow", return_value=23456):
            otp_core.store_otp(
                get_redis(), get_settings(), purpose=purpose, reference_id=reference_id, contact=contact
            )
        return "SM-SIGNUP-TEST"

    with (
        patch(
            "kavach_saathi.app.TwilioIntegrationClient.send_programmable_whatsapp_otp",
            side_effect=fake_whatsapp_otp,
        ) as whatsapp_send,
        patch("kavach_saathi.app.EmailIntegrationClient.send_otp_email") as email_send,
    ):
        response = client.post(
            "/v1/auth/signup",
            json={
                "role": "buyer",
                "name": "WhatsApp OTP Buyer",
                "password": "correct-horse-1",
                "phone": phone,
                "verification_channel": "whatsapp",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verification_sent"] is True
    assert body["verification_channel"] == "whatsapp"
    assert body["email_verification_sent"] is False
    whatsapp_send.assert_called_once()
    email_send.assert_not_called()

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    verified = client.post(
        "/v1/auth/verify-contact",
        headers=headers,
        json={"channel": "whatsapp", "otp": "123456"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["phone_verified"] is True


# --- Order confirmation via email (end to end) -------------------------------


def _signup(client, role: str, name: str) -> tuple[str, str]:
    email = _unique_email(role)
    response = client.post(
        "/v1/auth/signup",
        json={"role": role, "name": name, "password": "correct-horse-1", "email": email},
    )
    return response.json()["access_token"], email


def test_order_confirm_via_email_schedules_delivery(client) -> None:
    seller_token, _ = _signup(client, "seller", "Email OTP Seller")
    buyer_token, buyer_email = _signup(client, "buyer", "Email OTP Buyer Order")
    seller_headers = {"Authorization": f"Bearer {seller_token}"}
    buyer_headers = {"Authorization": f"Bearer {buyer_token}"}

    product = client.post(
        "/v1/seller/products",
        headers=seller_headers,
        json={
            "title": "Email OTP Test Kurta",
            "category": "Kurti, Saree & Lehenga",
            "price": 599,
            "original_price": 999,
            "image_keys": ["assets/mock/products/P-001.png"],
        },
    ).json()
    variant = client.post(
        f"/v1/seller/products/{product['id']}/variants",
        headers=seller_headers,
        json={"size": "M", "stock_qty": 5},
    ).json()
    client.post("/v1/cart", headers=buyer_headers, json={"product_variant_id": variant["id"], "qty": 1})

    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    fake_geo = {
        "label": "Test", "city": "Bilaspur", "district": "Bilaspur", "state": "Chhattisgarh", "postal_pin": "495001",
    }
    fake_lookup = SimpleNamespace(
        valid=True,
        phone_number="+919748572321",
        country_code="IN",
        line_type_intelligence={"carrier_name": "Airtel", "type": "mobile"},
    )
    phone_numbers = MagicMock()
    phone_numbers.fetch.return_value = fake_lookup
    twilio_client = MagicMock()
    twilio_client.lookups.v2.phone_numbers.return_value = phone_numbers
    geocode_target = "kavach_saathi.providers.google_maps.GoogleMapsGeocoder.reverse_geocode"
    with (
        patch(geocode_target, new=AsyncMock(return_value=fake_geo)),
        patch(
            "kavach_saathi.providers.twilio_integration.TwilioIntegrationClient.is_configured",
            new_callable=lambda: property(lambda self: True),
        ),
        patch("kavach_saathi.providers.twilio_integration.TwilioIntegrationClient._client", return_value=twilio_client),
    ):
        address = client.post(
            "/v1/addresses",
            headers=buyer_headers,
            json={
                "recipient_name": "Email OTP Buyer",
                "phone": "9748572321",
                "address_line1": "Test lane",
                "city": "Bilaspur",
                "district": "Bilaspur",
                "state": "Chhattisgarh",
                "postal_pin": "495001",
                "latitude": 22.0797,
                "longitude": 82.1409,
            },
        )
    assert address.status_code == 201, address.text

    order = client.post(
        "/v1/orders", headers=buyer_headers, json={"address_id": address.json()["id"], "payment_mode": "cod"}
    )
    assert order.status_code == 201
    order_id = order.json()["order_id"]

    smtp_instance = MagicMock()
    with (
        _email_configured(),
        patch("kavach_saathi.providers.otp_core.secrets.randbelow", return_value=23456),
        patch(SEND_OTP_TARGET) as smtp_cls,
    ):
        smtp_cls.return_value.__enter__.return_value = smtp_instance
        sent = client.post(f"/v1/orders/{order_id}/confirm/email/send", headers=buyer_headers)
        assert sent.status_code == 200

        wrong = client.post(
            f"/v1/orders/{order_id}/confirm/email/verify", headers=buyer_headers, json={"otp": "000000"}
        )
        assert wrong.status_code == 400

        confirmed = client.post(
            f"/v1/orders/{order_id}/confirm/email/verify", headers=buyer_headers, json={"otp": "123456"}
        )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "DELIVERY_SCHEDULED"
    assert body["promised_delivery_date"] is not None

    orders = client.get("/v1/orders", headers=buyer_headers).json()
    assert next(o for o in orders if o["id"] == order_id)["status"] == "DELIVERY_SCHEDULED"


# --- Delivery / return channel selection -------------------------------------


def _delivery_boy(client) -> tuple[str, str]:
    return _signup(client, "delivery_boy", "Email OTP Delivery Boy")


def test_delivery_otp_via_email_completes_delivery(client) -> None:
    from sqlalchemy import select

    from kavach_saathi.db.base import SessionLocal
    from kavach_saathi.db.models import Order, OrderItem, User
    from kavach_saathi.order_status import OrderStatus

    delivery_token, _ = _delivery_boy(client)
    _, buyer_email = _signup(client, "buyer", "Email OTP Delivery Buyer")
    order_id = f"O-EMAILDEL-{uuid.uuid4().hex[:8].upper()}"
    with SessionLocal() as session:
        buyer_id = session.execute(select(User).where(User.email == buyer_email)).scalars().first().id
        session.add(
            Order(
                id=order_id, buyer_id=buyer_id, status=OrderStatus.DELIVERY_SCHEDULED,
                total_amount=349.0, payment_mode="cod",
            )
        )
        session.add(
            OrderItem(
                order_id=order_id, product_id="P-001", product_variant_id=None, seller_id="S-001",
                size="M", qty=1, price_at_purchase=349.0,
            )
        )
        session.commit()

    headers = {"Authorization": f"Bearer {delivery_token}"}
    smtp_instance = MagicMock()
    with (
        _email_configured(),
        patch("kavach_saathi.providers.otp_core.secrets.randbelow", return_value=23456),
        patch(SEND_OTP_TARGET) as smtp_cls,
    ):
        smtp_cls.return_value.__enter__.return_value = smtp_instance
        sent = client.post(f"/v1/delivery/deliveries/{order_id}/otp/send", headers=headers, json={"channel": "email"})
        assert sent.status_code == 200
        smtp_instance.send_message.assert_called_once()

        evidence = client.post(
            f"/v1/delivery/deliveries/{order_id}/evidence",
            headers=headers,
            json={
                "front_image_key": "assets/mock/products/P-001.png",
                "back_image_key": "assets/mock/products/P-001.png",
                "idempotency_key": uuid.uuid4().hex,
            },
        )
        assert evidence.status_code == 200, evidence.text

        completed = client.post(
            f"/v1/delivery/deliveries/{order_id}/complete",
            headers=headers,
            json={"otp_code": "123456", "idempotency_key": uuid.uuid4().hex},
        )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "DELIVERED"


def test_return_otp_via_email_completes_return(client) -> None:
    from sqlalchemy import select

    from kavach_saathi.db.base import SessionLocal
    from kavach_saathi.db.models import Order, OrderItem, ReturnRecord, User
    from kavach_saathi.order_status import OrderStatus

    delivery_token, _ = _delivery_boy(client)
    _, buyer_email = _signup(client, "buyer", "Email OTP Return Buyer")
    order_id = f"O-EMAILRET-{uuid.uuid4().hex[:8].upper()}"
    return_id = f"RT-EMAILRET-{uuid.uuid4().hex[:8].upper()}"
    with SessionLocal() as session:
        buyer_id = session.execute(select(User).where(User.email == buyer_email)).scalars().first().id
        session.add(
            Order(id=order_id, buyer_id=buyer_id, status=OrderStatus.DELIVERED, total_amount=349.0, payment_mode="cod")
        )
        session.add(
            OrderItem(
                order_id=order_id, product_id="P-001", product_variant_id=None, seller_id="S-001",
                size="M", qty=1, price_at_purchase=349.0,
                delivery_front_image="assets/mock/products/P-001.png",
                delivery_back_image="assets/mock/products/P-001.png",
            )
        )
        session.add(
            ReturnRecord(
                id=return_id, order_id=order_id, product_id="P-001", buyer_id=buyer_id,
                reason="wrong size", return_type="refund", status="pending_return",
                similarity_aggregate=95.0, similarity_front=95.0, similarity_back=95.0,
            )
        )
        session.commit()

    headers = {"Authorization": f"Bearer {delivery_token}"}
    smtp_instance = MagicMock()
    with (
        _email_configured(),
        patch("kavach_saathi.providers.otp_core.secrets.randbelow", return_value=23456),
        patch(SEND_OTP_TARGET) as smtp_cls,
    ):
        smtp_cls.return_value.__enter__.return_value = smtp_instance
        sent = client.post(f"/v1/delivery/returns/{return_id}/otp/send", headers=headers, json={"channel": "email"})
        assert sent.status_code == 200
        smtp_instance.send_message.assert_called_once()

        completed = client.post(
            f"/v1/delivery/returns/{return_id}/complete",
            headers=headers,
            json={
                "otp_code": "123456",
                "idempotency_key": uuid.uuid4().hex,
                "inspection_checklist": {"matches_images": True, "seal_and_tags_present": True, "undamaged": True},
            },
        )
    assert completed.status_code == 200, completed.text

    with SessionLocal() as session:
        assert session.get(Order, order_id).status == OrderStatus.RETURN_APPROVED
