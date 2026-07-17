from __future__ import annotations

from kavach_saathi.app import app


def test_required_public_routes_are_documented() -> None:
    paths = app.openapi()["paths"]
    required = {
        "/v1/uploads/presign",
        "/v1/listings/analyze",
        "/v1/size/recommend",
        "/v1/reviews/analyze",
        "/v1/voice/query",
        "/v1/address/verify",
        "/v1/orders/{order_id}/confirm-simulated",
        "/v1/returns/analyze",
        "/v1/runs/{run_id}",
        "/v1/runs/{run_id}/events",
    }
    assert required <= set(paths)
