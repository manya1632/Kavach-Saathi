from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from collections import Counter
from time import perf_counter, time
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from kavach_saathi.config import Settings
from kavach_saathi.redis_client import increment_and_check_quota

logger = logging.getLogger("kavach_saathi.access")


# Limits are deliberately generous enough for normal UI retries and multi-tab use.
# The API contract is unchanged; only sustained automated abuse receives HTTP 429.
_RATE_LIMITS: dict[tuple[str, str], int] = {
    # Unauthenticated users may share one carrier-grade NAT address, so these two
    # IP-scoped thresholds are intentionally broad. Authenticated limits below use
    # a one-way token fingerprint and are much more precise.
    ("POST", "/v1/auth/login"): 300,
    ("POST", "/v1/auth/signup"): 100,
    ("POST", "/v1/addresses/otp/send"): 5,
    ("POST", "/v1/voice/query"): 30,
    ("POST", "/v1/chat/messages"): 30,
    ("POST", "/v1/orders"): 20,
    ("POST", "/v1/uploads/presign"): 60,
    ("POST", "/v1/reviews"): 10,
}

_DYNAMIC_RATE_LIMITS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("POST", re.compile(r"^/v1/delivery/(?:deliveries|returns)/[^/]+/otp/send$"), 10),
    ("POST", re.compile(r"^/v1/returns/[^/]+/image-attempt$"), 10),
)


class RequestMetrics:
    """Small process-local counters suitable for health dashboards and scraping.

    They intentionally contain no user identifiers, request bodies, tokens, or OTPs.
    A production deployment can scrape each instance and aggregate externally.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: Counter[str] = Counter()
        self._latency_ms_total: Counter[str] = Counter()

    def observe(self, method: str, route: str, status_code: int, latency_ms: int) -> None:
        key = f"{method} {route} {status_code // 100}xx"
        with self._lock:
            self._requests[key] += 1
            self._latency_ms_total[key] += latency_ms

    def snapshot(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {
                "requests": dict(self._requests),
                "latency_ms_total": dict(self._latency_ms_total),
            }

    def prometheus(self, *, labels: dict[str, str] | None = None) -> str:
        """Render dependency-free Prometheus text without changing the JSON endpoint."""
        labels = labels or {}
        with self._lock:
            requests = dict(self._requests)
            latency = dict(self._latency_ms_total)

        def _labels(extra: dict[str, Any]) -> str:
            values = {**labels, **extra}
            encoded = ",".join(
                f'{key}="{str(value).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
                for key, value in sorted(values.items())
            )
            return f"{{{encoded}}}" if encoded else ""

        lines = [
            "# HELP kavach_http_requests_total HTTP requests grouped by method, route and status class.",
            "# TYPE kavach_http_requests_total counter",
        ]
        for key, count in sorted(requests.items()):
            method, route, status_class = key.split(" ", 2)
            metric_labels = _labels({"method": method, "route": route, "status_class": status_class})
            lines.append(f"kavach_http_requests_total{metric_labels} {count}")
        lines.extend(
            [
                "# HELP kavach_http_latency_milliseconds_total Accumulated HTTP request latency.",
                "# TYPE kavach_http_latency_milliseconds_total counter",
            ]
        )
        for key, total in sorted(latency.items()):
            method, route, status_class = key.split(" ", 2)
            metric_labels = _labels({"method": method, "route": route, "status_class": status_class})
            lines.append(f"kavach_http_latency_milliseconds_total{metric_labels} {total}")
        return "\n".join(lines) + "\n"


request_metrics = RequestMetrics()


def _rate_limit_identity(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization:
        return "token:" + hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:24]
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


def _rate_limit_for(method: str, path: str) -> int | None:
    exact = _RATE_LIMITS.get((method, path))
    if exact is not None:
        return exact
    for expected_method, pattern, limit in _DYNAMIC_RATE_LIMITS:
        if method == expected_method and pattern.fullmatch(path):
            return limit
    return None


async def operational_middleware(request: Request, call_next, settings: Settings):
    request_id = request.headers.get("x-request-id", "").strip()[:128] or str(uuid4())
    request.state.request_id = request_id
    started = perf_counter()

    limit = _rate_limit_for(request.method, request.url.path) if settings.rate_limit_enabled else None
    if limit:
        identity = _rate_limit_identity(request)
        bucket = int(time() // settings.rate_limit_window_seconds)
        key = f"rate:{request.method}:{request.url.path}:{identity}:{bucket}"
        try:
            _count, allowed = increment_and_check_quota(
                key,
                limit=limit,
                ttl_seconds=settings.rate_limit_window_seconds + 5,
            )
            if not allowed:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again shortly."},
                    headers={"Retry-After": str(settings.rate_limit_window_seconds)},
                )
                response.headers["X-Request-ID"] = request_id
                return response
        except Exception:
            logger.warning("Rate limiter unavailable; request allowed", exc_info=True)

    try:
        response = await call_next(request)
    except Exception:
        latency_ms = round((perf_counter() - started) * 1000)
        logger.exception(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": 500,
                    "latency_ms": latency_ms,
                }
            )
        )
        request_metrics.observe(request.method, request.url.path, 500, latency_ms)
        raise

    latency_ms = round((perf_counter() - started) * 1000)
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    request_metrics.observe(request.method, route_path, response.status_code, latency_ms)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": route_path,
                "status": response.status_code,
                "latency_ms": latency_ms,
            }
        )
    )
    return response
