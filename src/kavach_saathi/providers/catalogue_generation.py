from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from kavach_saathi.config import Settings
from kavach_saathi.media_storage import read_image_bytes, write_generated_image
from kavach_saathi.providers.fashn_api import FashnApiClient, FashnApiUnavailable
from kavach_saathi.providers.fashn_vton import FashnVtonClient, FashnVtonUnavailable, category_for_product
from kavach_saathi.providers.huggingface_image import HuggingFaceImageClient, HuggingFaceImageUnavailable
from kavach_saathi.providers.nano_banana import NanoBananaClient, NanoBananaQuotaExceeded, NanoBananaUnavailable
from kavach_saathi.providers.segmentation import GarmentSegmenter
from kavach_saathi.providers.stable_diffusion_fallback import StableDiffusionFallback
from kavach_saathi.redis_client import increment_and_check_quota

VIEWS = ("front", "back", "left", "right")


class CatalogueImageGenerator:
    """Agent 1's real image-gen pipeline (final target plan.md Section 6):
    SAM 2.0 segmentation -> FASHN's own paid Try-On v1.6 API (primary: first-party,
    commercially licensed, metered, no cold starts/quota ceiling) -> Nano Banana 2
    (Gemini, kept in case its quota is ever restored) -> the free FASHN Hugging Face
    Space (maskless virtual try-on, same model as the paid tier, used only if paid
    credits run out) -> Hugging Face Inference API (FLUX.1 Kontext) -> self-hosted
    Stable Diffusion + ControlNet (CPU) last-resort fallback, all conditioned on the
    same segmented garment so output stays visually consistent regardless of which
    provider actually served the request.

    Only applies to wearable garments. If the seller marked the product as not a
    garment (bags, footwear, jewellery, etc. -- garment_target == "none"), there is
    no "model wearing it" to generate, so the seller's own photo is used as-is.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.segmenter = GarmentSegmenter(settings)
        self.fashn_api = FashnApiClient(settings)
        self.nano_banana = NanoBananaClient(settings)
        self.fashn = FashnVtonClient(settings)
        self.huggingface = HuggingFaceImageClient(settings)
        self.sd_fallback = StableDiffusionFallback(settings)

    async def generate(self, image_keys: list[str], product: dict[str, Any]) -> list[dict[str, Any]]:
        garment_target = (product.get("specs") or {}).get("garment_target", "woman")
        if garment_target == "none":
            # Not a wearable garment -- there's no "model wearing it" to generate at
            # all, so the seller's own photos *are* the finished catalogue images,
            # not a pending intermediate state. Use each of the seller's actual
            # uploaded photos (reusing the last one if fewer than 4 were provided)
            # rather than repeating a single image across all 4 angle slots --
            # marking all 4 complete here also keeps the verified-listing
            # badge/sort from perpetually reading this as stuck awaiting an AI step
            # that was never applicable in the first place.
            # `image_keys` here is the single primary image the workflow was started
            # with, not the seller's full 2-4 product photos -- those live on the
            # product record itself.
            photos = product.get("product_images") or image_keys
            return [
                {
                    "view": view,
                    "key": photos[index] if index < len(photos) else photos[-1],
                    "provider": "original_upload",
                    "nano_banana_quota_count": None,
                    "nano_banana_daily_quota": self.settings.nano_banana_daily_quota,
                }
                for index, view in enumerate(VIEWS)
            ]

        source_bytes = await read_image_bytes(image_keys[0], self.settings)
        garment_png = await asyncio.to_thread(self.segmenter.segment, source_bytes)
        fashn_category = category_for_product(product.get("category", ""))

        quota_key = f"nano_banana_quota:{date.today().isoformat()}"
        seed_base = int(datetime.now(UTC).strftime("%Y%m%d"))

        results: list[dict[str, Any]] = []
        for index, view in enumerate(VIEWS):
            provider_used: str | None = None
            image_bytes: bytes | None = None
            quota_count: int | None = None

            if self.settings.fashn_api_key:
                try:
                    image_bytes = await self.fashn_api.generate_view(garment_png, view, garment_target, fashn_category)
                    provider_used = "fashn_api"
                except FashnApiUnavailable:
                    image_bytes = None

            if image_bytes is None and self.settings.gemini_api_key:
                quota_count, within_quota = increment_and_check_quota(
                    quota_key, limit=self.settings.nano_banana_daily_quota
                )
                if within_quota:
                    try:
                        image_bytes = await self.nano_banana.generate_view(garment_png, view)
                        provider_used = "nano_banana_2"
                    except (NanoBananaQuotaExceeded, NanoBananaUnavailable):
                        image_bytes = None

            if image_bytes is None and self.settings.huggingface_api_key:
                try:
                    image_bytes = await self.fashn.generate_view(garment_png, view, garment_target, fashn_category)
                    provider_used = "fashn_vton"
                except FashnVtonUnavailable:
                    image_bytes = None

            if image_bytes is None and self.settings.huggingface_api_key:
                try:
                    image_bytes = await self.huggingface.generate_view(garment_png, view)
                    provider_used = "huggingface_flux_kontext"
                except HuggingFaceImageUnavailable:
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
