from __future__ import annotations

from functools import lru_cache

import redis

from kavach_saathi.config import Settings, get_settings


@lru_cache
def get_redis(settings: Settings | None = None) -> redis.Redis:
    settings = settings or get_settings()
    return redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
        retry_on_timeout=settings.redis_retry_on_timeout,
        health_check_interval=30,
    )


@lru_cache
def get_cache_redis(settings: Settings | None = None) -> redis.Redis:
    settings = settings or get_settings()
    return redis.from_url(
        settings.redis_cache_url or settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
        retry_on_timeout=settings.redis_retry_on_timeout,
        health_check_interval=30,
    )


@lru_cache
def get_stream_redis(settings: Settings | None = None) -> redis.Redis:
    """Dedicated client for Redis Stream blocking reads.

    General Redis commands retain a bounded socket timeout. XREADGROUP instead uses
    Redis's own BLOCK interval, so a client-side read timeout would create false
    failures during normal idle periods.
    """
    settings = settings or get_settings()
    return redis.from_url(
        settings.redis_stream_url or settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_max_connections,
        socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
        socket_timeout=None,
        retry_on_timeout=settings.redis_retry_on_timeout,
        health_check_interval=30,
    )


def increment_and_check_quota(
    key: str, *, limit: int, ttl_seconds: int = 90_000, client: redis.Redis | None = None
) -> tuple[int, bool]:
    """Atomically increment a daily counter and report whether it's still within quota.

    Returns (count_after_increment, within_quota). The key is expired after `ttl_seconds`
    (default just over a day) so quota counters reset daily without a cron job.
    """
    client = client or get_redis()
    pipe = client.pipeline()
    pipe.incr(key)
    pipe.expire(key, ttl_seconds, nx=True)
    count, _ = pipe.execute()
    return int(count), int(count) <= limit
