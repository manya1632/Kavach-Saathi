from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from uuid import uuid4

from kavach_saathi.redis_client import get_cache_redis

logger = logging.getLogger(__name__)

_VERSION_KEY = "cache:catalogue:version"


def _version() -> str | None:
    try:
        client = get_cache_redis()
        version = client.get(_VERSION_KEY)
        if version:
            return str(version)
        candidate = uuid4().hex
        client.set(_VERSION_KEY, candidate, nx=True)
        return str(client.get(_VERSION_KEY) or candidate)
    except Exception:
        logger.warning("Catalogue cache unavailable; using database", exc_info=True)
        return None


def _key(namespace: str, parts: tuple[Any, ...]) -> str | None:
    version = _version()
    if version is None:
        return None
    raw = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"cache:catalogue:{version}:{namespace}:{digest}"


def get_catalogue_cache(namespace: str, *parts: Any) -> Any | None:
    key = _key(namespace, parts)
    if key is None:
        return None
    try:
        cached = get_cache_redis().get(key)
        return json.loads(cached) if cached else None
    except Exception:
        logger.warning("Catalogue cache read failed; using database", exc_info=True)
        return None


def set_catalogue_cache(value: Any, namespace: str, *parts: Any, ttl_seconds: int = 60) -> None:
    key = _key(namespace, parts)
    if key is None:
        return
    try:
        get_cache_redis().setex(key, ttl_seconds, json.dumps(value, default=str, separators=(",", ":")))
    except Exception:
        logger.warning("Catalogue cache write failed; response remains valid", exc_info=True)


def invalidate_catalogue_cache() -> None:
    """Rotate the namespace after a committed catalogue-affecting transaction."""
    try:
        get_cache_redis().set(_VERSION_KEY, uuid4().hex)
    except Exception:
        logger.warning("Catalogue cache invalidation failed; entries will expire shortly", exc_info=True)
