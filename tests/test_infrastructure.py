from __future__ import annotations

from unittest.mock import MagicMock

from kavach_saathi.config import Settings


def test_database_engine_passes_managed_postgres_safety_options(monkeypatch) -> None:
    from kavach_saathi.db import base

    settings = Settings(
        database_ssl_mode="require",
        database_connect_timeout_seconds=7,
        database_statement_timeout_ms=12_000,
        database_application_name="kavach-test",
    )
    captured = {}
    marker = MagicMock()

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return marker

    monkeypatch.setattr(base, "get_settings", lambda: settings)
    monkeypatch.setattr(base, "create_engine", fake_create_engine)

    result = base._create_database_engine(settings.database_url, pool_size=4)
    assert result is marker
    assert captured["pool_size"] == 4
    assert captured["pool_pre_ping"] is True
    assert captured["pool_use_lifo"] is True
    assert captured["connect_args"] == {
        "connect_timeout": 7,
        "application_name": "kavach-test",
        "sslmode": "require",
        "options": "-c statement_timeout=12000",
    }


def test_redis_clients_can_be_split_without_changing_default(monkeypatch) -> None:
    from kavach_saathi import redis_client

    settings = Settings(
        redis_url="redis://primary/0",
        redis_cache_url="redis://cache/0",
        redis_stream_url="redis://streams/0",
    )
    urls = []

    def fake_from_url(url, **_kwargs):
        urls.append(url)
        return MagicMock()

    monkeypatch.setattr(redis_client, "get_settings", lambda: settings)
    monkeypatch.setattr(redis_client.redis, "from_url", fake_from_url)
    redis_client.get_redis.cache_clear()
    redis_client.get_cache_redis.cache_clear()
    redis_client.get_stream_redis.cache_clear()
    try:
        redis_client.get_redis()
        redis_client.get_cache_redis()
        redis_client.get_stream_redis()
    finally:
        redis_client.get_redis.cache_clear()
        redis_client.get_cache_redis.cache_clear()
        redis_client.get_stream_redis.cache_clear()

    assert urls == ["redis://primary/0", "redis://cache/0", "redis://streams/0"]
