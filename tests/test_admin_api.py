from __future__ import annotations

import uuid


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@pytest.kavachsaathi.test"


def _admin_headers(client) -> dict:
    login = client.post(
        "/v1/auth/login",
        json={"identifier": "admin@kavachsaathi.test", "password": "KavachDemo@2026"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _buyer_headers(client) -> dict:
    email = _unique_email("admin-guard-buyer")
    signup = client.post(
        "/v1/auth/signup",
        json={"role": "buyer", "name": "Guard Buyer", "password": "correct-horse-1", "email": email},
    )
    return {"Authorization": f"Bearer {signup.json()['access_token']}"}


def test_admin_endpoints_require_admin_role(client) -> None:
    buyer_headers = _buyer_headers(client)
    for method, path in (
        ("get", "/v1/admin/inspection-queue"),
        ("get", "/v1/admin/fraud-cases"),
        ("get", "/v1/admin/analytics"),
        ("post", "/v1/admin/trust-scores/recompute"),
    ):
        response = getattr(client, method)(path, headers=buyer_headers)
        assert response.status_code == 403, f"{method} {path} should be admin-only"


def test_admin_analytics_reports_real_counts(client) -> None:
    headers = _admin_headers(client)
    response = client.get("/v1/admin/analytics", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_orders"] >= 1
    assert isinstance(body["avg_confidence_by_agent"], dict)


def test_admin_fraud_cases_reflects_real_flags(client) -> None:
    headers = _admin_headers(client)
    response = client.get("/v1/admin/fraud-cases", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "stolen_photo_products",
        "manual_inspection_returns",
        "flagged_sellers",
        "flagged_buyers",
    }


def test_admin_can_override_seller_trust_score(client) -> None:
    headers = _admin_headers(client)
    response = client.patch(
        "/v1/admin/sellers/S-001/trust-score",
        headers=headers,
        json={"trust_score": 42.5, "verified": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trust_score"] == 42.5
    assert body["verified"] is True


def test_admin_trust_score_override_404s_for_unknown_seller(client) -> None:
    headers = _admin_headers(client)
    response = client.patch(
        "/v1/admin/sellers/S-DOES-NOT-EXIST/trust-score",
        headers=headers,
        json={"trust_score": 10},
    )
    assert response.status_code == 404


def test_admin_recompute_trust_scores_updates_all(client) -> None:
    headers = _admin_headers(client)
    response = client.post("/v1/admin/trust-scores/recompute", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["sellers_updated"] >= 1
    assert body["buyers_updated"] >= 1


def test_admin_resolve_return_404s_for_unknown_return(client) -> None:
    headers = _admin_headers(client)
    response = client.post(
        "/v1/admin/returns/RT-DOES-NOT-EXIST/resolve",
        headers=headers,
        json={"decision": "approve"},
    )
    assert response.status_code == 404
