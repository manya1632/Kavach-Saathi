from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from kavach_saathi.config import Settings
from kavach_saathi.media_storage import read_image_bytes, write_generated_image
from kavach_saathi.providers.nano_banana import NanoBananaClient, NanoBananaQuotaExceeded, NanoBananaUnavailable
from kavach_saathi.providers.segmentation import GarmentSegmenter
from kavach_saathi.providers.stable_diffusion_fallback import StableDiffusionFallback
from kavach_saathi.redis_client import increment_and_check_quota

VIEWS = ("front", "back", "left", "right")


class CatalogueImageGenerator:
    """Agent 1's real image-gen pipeline (final target plan.md Section 6):
    SAM 2.0 segmentation -> Nano Banana 2 (Gemini) primary generation, with a
    Redis-tracked daily quota and an automatic Stable Diffusion + ControlNet fallback,
    conditioned on the same segmented garment so output stays visually consistent
    regardless of which provider actually served the request.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.segmenter = GarmentSegmenter(settings)
        self.nano_banana = NanoBananaClient(settings)
        self.sd_fallback = StableDiffusionFallback(settings)

    async def generate(self, image_keys: list[str], product: dict[str, Any]) -> list[dict[str, Any]]:
        source_bytes = await read_image_bytes(image_keys[0], self.settings)
        garment_png = await asyncio.to_thread(self.segmenter.segment, source_bytes)

        quota_key = f"nano_banana_quota:{date.today().isoformat()}"
        seed_base = int(datetime.now(UTC).strftime("%Y%m%d"))

        results: list[dict[str, Any]] = []
        for index, view in enumerate(VIEWS):
            provider_used: str | None = None
            image_bytes: bytes | None = None
            quota_count: int | None = None

            if self.settings.gemini_api_key:
                quota_count, within_quota = increment_and_check_quota(
                    quota_key, limit=self.settings.nano_banana_daily_quota
                )
                if within_quota:
                    try:
                        image_bytes = await self.nano_banana.generate_view(garment_png, view)
                        provider_used = "nano_banana_2"
                    except (NanoBananaQuotaExceeded, NanoBananaUnavailable):
                        image_bytes = None

            if image_bytes is None:
                image_bytes = await self.sd_fallback.generate_view(garment_png, view, seed=seed_base + index)
                provider_used = "stable_diffusion_controlnet"

            key = f"generated/catalog/{product['id']}-{view}.png"
            write_generated_image(key, image_bytes, self.settings)
            results.append(
                {
                    "view": view,
                    "key": key,
                    "provider": provider_used,
                    "nano_banana_quota_count": quota_count,
                    "nano_banana_daily_quota": self.settings.nano_banana_daily_quota,
                }
            )
        return results
