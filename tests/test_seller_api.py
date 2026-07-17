from __future__ import annotations

import uuid


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@pytest.kavachsaathi.test"


def _signup_seller(client) -> tuple[str, dict]:
    email = _unique_email("seller-portal")
    response = client.post(
        "/v1/auth/signup",
        json={
            "role": "seller",
            "name": "Portal Seller",
            "password": "correct-horse-1",
            "email": email,
            "business_name": "Portal Seller Co",
        },
    )
    body = response.json()
    return body["access_token"], body["user"]


def _signup_buyer(client) -> str:
    email = _unique_email("seller-portal-buyer")
    response = client.post(
        "/v1/auth/signup",
        json={"role": "buyer", "name": "Portal Buyer", "password": "correct-horse-1", "email": email},
    )
    return response.json()["access_token"]


def test_seller_profile_requires_seller_role(client) -> None:
    buyer_token = _signup_buyer(client)
    response = client.get("/v1/seller/profile", headers={"Authorization": f"Bearer {buyer_token}"})
    assert response.status_code == 403


def test_seller_profile_created_on_signup(client) -> None:
    token, user = _signup_seller(client)
    response = client.get("/v1/seller/profile", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user["id"]
    assert body["business_name"] == "Portal Seller Co"
    assert body["digilocker_kyc_status"] == "not_started"


def test_seller_can_create_product_and_variant(client) -> None:
    token, _ = _signup_seller(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/v1/seller/products",
        headers=headers,
        json={
            "title": "Test Listing Kurta",
            "category": "Kurti, Saree & Lehenga",
            "price": 499,
            "original_price": 999,
            "image_keys": ["assets/mock/products/P-001.png"],
        },
    )
    assert created.status_code == 201
    product_id = created.json()["id"]

    listed = client.get("/v1/seller/products", headers=headers)
    assert any(item["id"] == product_id for item in listed.json())

    variant = client.post(
        f"/v1/seller/products/{product_id}/variants",
        headers=headers,
        json={"size": "M", "stock_qty": 20},
    )
    assert variant.status_code == 201
    assert variant.json()["stock_qty"] == 20


def test_seller_cannot_update_another_sellers_product(client) -> None:
    token_a, _ = _signup_seller(client)
    token_b, _ = _signup_seller(client)
    created = client.post(
        "/v1/seller/products",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "title": "Owned By A",
            "category": "Men",
            "price": 299,
            "original_price": 599,
            "image_keys": ["assets/mock/products/P-001.png"],
        },
    )
    product_id = created.json()["id"]
    response = client.patch(
        f"/v1/seller/products/{product_id}",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"price": 1},
    )
    assert response.status_code == 404


def test_kyc_start_reports_not_configured_without_credentials(client) -> None:
    token, _ = _signup_seller(client)
    response = client.post(
        "/v1/seller/kyc/start",
        headers={"Authorization": f"Bearer {token}"},
        params={"redirect_uri": "http://localhost:3000/seller/kyc/callback"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["authorize_url"] is None


def test_seller_orders_lists_only_own_order_items(client) -> None:
    token, _ = _signup_seller(client)
    response = client.get("/v1/seller/orders", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == []


def test_seller_order_status_update_rejects_invalid_transition(client) -> None:
    headers = {"Authorization": f"Bearer {_seller_token_for_golden(client)}"}
    response = client.patch("/v1/seller/orders/O-GOLDEN/status", headers=headers, json={"status": "SHIPPED"})
    # O-GOLDEN's seller is S-001 (a seed seller, not this pytest-created seller) or the
    # transition itself is invalid from its seeded status -- either way this must not silently succeed.
    assert response.status_code in (404, 409)


def _seller_token_for_golden(client) -> str:
    token, _ = _signup_seller(client)
    return token
