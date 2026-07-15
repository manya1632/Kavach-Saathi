from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from kavach_saathi.config import Settings
from kavach_saathi.providers.catalogue_generation import CatalogueImageGenerator


class MediaProvider(ABC):
    @abstractmethod
    async def analyze_images(
        self, image_keys: list[str], prompt: str, ground_truth: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def analyze_video(
        self, video_key: str, prompt: str, ground_truth: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def generate_catalog_views(self, image_keys: list[str], product: dict[str, Any]) -> list[dict[str, Any]]: ...


class DemoMediaProvider(MediaProvider):
    def __init__(self, settings: Settings):
        self.settings = settings
        self._generator = CatalogueImageGenerator(settings)

    async def analyze_images(
        self, image_keys: list[str], prompt: str, ground_truth: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return ground_truth or {"quality": 0.9, "matches_product": True}

    async def analyze_video(
        self, video_key: str, prompt: str, ground_truth: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return ground_truth or {
            "tag_visible": True,
            "label_matches": True,
            "product_matches": True,
            "packaging_matches": True,
        }

    async def generate_catalog_views(self, image_keys: list[str], product: dict[str, Any]) -> list[dict[str, Any]]:
        # Real pipeline (SAM 2.0 -> Nano Banana 2 -> Stable Diffusion fallback) even in
        # demo mode -- there is no fixture-path shortcut for image generation anymore.
        return await self._generator.generate(image_keys, product)


class BedrockMediaProvider(MediaProvider):
    def __init__(self, settings: Settings):
        import boto3

        self.settings = settings
        self.client = boto3.client("bedrock-runtime", region_name=settings.aws_region)
        self._generator = CatalogueImageGenerator(settings)

    def _s3_uri(self, key: str) -> str:
        return key if key.startswith("s3://") else f"s3://{self.settings.media_bucket}/{key}"

    async def analyze_images(
        self, image_keys: list[str], prompt: str, ground_truth: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        for key in image_keys:
            content.append(
                {
                    "image": {
                        "format": key.rsplit(".", 1)[-1].replace("jpg", "jpeg"),
                        "source": {"s3Location": {"uri": self._s3_uri(key)}},
                    }
                }
            )
        content.append({"text": prompt + " Return only JSON."})
        response = self.client.converse(
            modelId=self.settings.nova_model_id,
            messages=[{"role": "user", "content": content}],
            inferenceConfig={"temperature": 0, "maxTokens": 1500},
        )
        text = response["output"]["message"]["content"][0]["text"]
        return json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())

    async def analyze_video(
        self, video_key: str, prompt: str, ground_truth: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        fmt = video_key.rsplit(".", 1)[-1].replace("mp4", "mp4")
        response = self.client.converse(
            modelId=self.settings.nova_model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "video": {
                                "format": fmt,
                                "source": {"s3Location": {"uri": self._s3_uri(video_key)}},
                            }
                        },
                        {"text": prompt + " Return only JSON."},
                    ],
                }
            ],
            inferenceConfig={"temperature": 0, "maxTokens": 2000},
        )
        text = response["output"]["message"]["content"][0]["text"]
        return json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())

    async def generate_catalog_views(self, image_keys: list[str], product: dict[str, Any]) -> list[dict[str, Any]]:
        # Replaces the old Nova Canvas VIRTUAL_TRY_ON path (gap_report B9): Agent 1's
        # image generator is now Nano Banana 2 with a Stable Diffusion fallback, per the
        # plan, in both demo and live mode.
        return await self._generator.generate(image_keys, product)
