from __future__ import annotations

from unittest.mock import MagicMock

import redis

from kavach_saathi.catalog_cache import get_catalogue_cache, invalidate_catalogue_cache, set_catalogue_cache
from kavach_saathi.events import _process_message, _restore_missing_group


def test_request_id_is_returned_and_metrics_are_available(client) -> None:
    response = client.get("/health", headers={"X-Request-ID": "pytest-request-id"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "pytest-request-id"

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    body = metrics.json()
    assert body["requests"]
    assert body["latency_ms_total"]

    prometheus = client.get("/metrics/prometheus")
    assert prometheus.status_code == 200
    assert "kavach_http_requests_total" in prometheus.text
    assert 'environment="local"' in prometheus.text


def test_liveness_does_not_depend_on_external_services(client) -> None:
    response = client.get("/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_checks_database_and_redis(client) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"] == {"database": True, "redis": True}


def test_rate_limit_returns_stable_error_and_retry_header(client, monkeypatch) -> None:
    monkeypatch.setattr("kavach_saathi.operational.increment_and_check_quota", lambda *args, **kwargs: (31, False))
    response = client.post("/v1/auth/login", json={"identifier": "nobody@example.com", "password": "password"})
    assert response.status_code == 429
    assert response.json() == {"detail": "Too many requests. Please try again shortly."}
    assert response.headers["Retry-After"] == "60"
    assert response.headers["X-Request-ID"]


def test_storefront_pagination_is_opt_in_and_preserves_total(client) -> None:
    full = client.get("/v1/storefront/products?limit=500")
    page = client.get("/v1/storefront/products?limit=2&offset=1")
    assert full.status_code == page.status_code == 200
    assert page.json()["total"] == full.json()["total"]
    assert page.json()["items"] == full.json()["items"][1:3]


def test_catalogue_cache_is_versioned_and_invalidated() -> None:
    invalidate_catalogue_cache()
    set_catalogue_cache({"items": ["P-001"]}, "pytest", "all")
    assert get_catalogue_cache("pytest", "all") == {"items": ["P-001"]}
    invalidate_catalogue_cache()
    assert get_catalogue_cache("pytest", "all") is None


def test_committed_product_change_automatically_invalidates_catalogue_cache() -> None:
    from kavach_saathi.db.base import SessionLocal
    from kavach_saathi.db.models import Product

    invalidate_catalogue_cache()
    set_catalogue_cache({"id": "P-001"}, "pytest-product", "P-001")
    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        assert product is not None
        original = product.delivery_days
        try:
            product.delivery_days = original + 1
            session.commit()
            assert get_catalogue_cache("pytest-product", "P-001") is None
        finally:
            product.delivery_days = original
            session.commit()


def test_failed_stream_message_moves_to_dead_letter_after_bounded_retries(monkeypatch) -> None:
    redis = MagicMock()
    redis.incr.side_effect = [1, 2, 3]
    monkeypatch.setattr("kavach_saathi.events.time.sleep", lambda _seconds: None)

    async def fail(_payload):
        raise RuntimeError("temporary provider failure")

    for _attempt in range(3):
        _process_message(
            redis,
            "events:test",
            "test-group",
            "1-0",
            {"data": '{"entity_id":"safe-id"}'},
            fail,
        )

    assert redis.xack.call_count == 1
    redis.xadd.assert_called_once()
    assert redis.xadd.call_args.args[0] == "events:test.dead-letter"


def test_missing_stream_group_is_recreated() -> None:
    client = MagicMock()
    assert _restore_missing_group(client, "events:test", "test-group", redis.ResponseError("NOGROUP missing"))
    client.xgroup_create.assert_called_once_with("events:test", "test-group", id="0", mkstream=True)
