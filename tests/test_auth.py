from __future__ import annotations

import uuid


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@pytest.kavachsaathi.test"


def test_buyer_signup_login_me_flow(client) -> None:
    email = _unique_email("buyer")
    signup = client.post(
        "/v1/auth/signup",
        json={
            "role": "buyer",
            "name": "Test Buyer",
            "password": "correct-horse-1",
            "preferred_language": "hi",
            "email": email,
        },
    )
    assert signup.status_code == 201
    body = signup.json()
    assert body["user"]["role"] == "buyer"
    assert body["user"]["preferred_language"] == "hi"
    access_token = body["access_token"]

    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email

    login = client.post("/v1/auth/login", json={"identifier": email, "password": "correct-horse-1"})
    assert login.status_code == 200
    assert login.json()["user"]["id"] == body["user"]["id"]


def test_login_rejects_wrong_password(client) -> None:
    email = _unique_email("wrongpw")
    client.post(
        "/v1/auth/signup",
        json={"role": "buyer", "name": "Wrong Pw", "password": "correct-horse-1", "email": email},
    )
    response = client.post("/v1/auth/login", json={"identifier": email, "password": "not-the-password"})
    assert response.status_code == 401


def test_signup_seller_creates_seller_profile(client) -> None:
    email = _unique_email("seller")
    response = client.post(
        "/v1/auth/signup",
        json={
            "role": "seller",
            "name": "Test Seller",
            "password": "correct-horse-1",
            "email": email,
            "business_name": "Test Seller Co",
        },
    )
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "seller"


def test_duplicate_signup_conflicts(client) -> None:
    email = _unique_email("dupe")
    payload = {"role": "buyer", "name": "Dupe", "password": "correct-horse-1", "email": email}
    first = client.post("/v1/auth/signup", json=payload)
    assert first.status_code == 201
    second = client.post("/v1/auth/signup", json=payload)
    assert second.status_code == 409


def test_refresh_token_rotates(client) -> None:
    email = _unique_email("refresh")
    signup = client.post(
        "/v1/auth/signup",
        json={"role": "buyer", "name": "Refresh Case", "password": "correct-horse-1", "email": email},
    )
    refresh_token = signup.json()["refresh_token"]
    rotated = client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != refresh_token

    reused = client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert reused.status_code == 401


def test_me_requires_bearer_token(client) -> None:
    response = client.get("/v1/auth/me")
    assert response.status_code == 401


def test_language_update_requires_auth_and_persists(client) -> None:
    email = _unique_email("lang")
    signup = client.post(
        "/v1/auth/signup",
        json={"role": "buyer", "name": "Lang Case", "password": "correct-horse-1", "email": email},
    )
    token = signup.json()["access_token"]
    updated = client.patch(
        "/v1/auth/language",
        params={"language": "bn"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert updated.status_code == 200
    assert updated.json()["preferred_language"] == "bn"

    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["preferred_language"] == "bn"
