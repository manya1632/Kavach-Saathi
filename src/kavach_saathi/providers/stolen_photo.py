from __future__ import annotations

import base64
from typing import Any

import httpx

from kavach_saathi.config import Settings

_VISION_URL = "https://vision.googleapis.com/v1/images:annotate"


class GoogleVisionUnavailable(RuntimeError):
    pass


class GoogleVisionReverseImageSearch:
    """Real Google Cloud Vision Web Detection for Agent 1's stolen-photo check (final
    target plan.md Section 6) -- replaces the previous ground_truth fixture
    pass-through, which always returned an empty match list regardless of the
    uploaded photo (the `ground_truth` field it read no longer exists on the Postgres
    `products` table since Sub-phase 0's fixture-stripping migration, so it was
    silently constant). Uses the plain REST endpoint with a simple API key rather than
    the google-cloud-vision client's service-account flow -- the same
    GOOGLE_MAPS_API_KEY project works here too once Cloud Vision API is enabled on it,
    no separate service account needed. Config-gated on GOOGLE_VISION_API_KEY; callers
    must catch GoogleVisionUnavailable and degrade honestly rather than fabricate a
    "no match" result.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.google_vision_api_key)

    async def search(self, image_bytes: bytes) -> dict[str, Any]:
        if not self.is_configured:
            raise GoogleVisionUnavailable("GOOGLE_VISION_API_KEY is not configured")

        payload = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
                    "features": [{"type": "WEB_DETECTION"}],
                }
            ]
        }
        async with httpx.AsyncClient(timeout=self.settings.provider_timeout_seconds) as client:
            response = await client.post(
                _VISION_URL, params={"key": self.settings.google_vision_api_key}, json=payload
            )
            response.raise_for_status()
            body = response.json()

        result = (body.get("responses") or [{}])[0]
        if "error" in result:
            raise GoogleVisionUnavailable(f"Google Vision returned an error: {result['error'].get('message')}")

        detection = result.get("webDetection", {})
        return {
            "full_matches": [item["url"] for item in detection.get("fullMatchingImages", [])],
            "partial_matches": [item["url"] for item in detection.get("partialMatchingImages", [])],
            "pages": [item["url"] for item in detection.get("pagesWithMatchingImages", [])],
        }
