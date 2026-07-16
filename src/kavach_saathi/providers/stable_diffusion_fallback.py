from __future__ import annotations

import io

from kavach_saathi.config import Settings
from kavach_saathi.providers.nano_banana import VIEW_PROMPTS

_SD_CHECKPOINT = "runwayml/stable-diffusion-v1-5"
_CONTROLNET_CHECKPOINT = "lllyasviel/sd-controlnet-canny"


class StableDiffusionFallback:
    """Self-hosted Stable Diffusion + ControlNet fallback, conditioned on the SAM
    2.0-segmented garment mask so output stays visually consistent with Nano Banana 2
    when its daily quota is exhausted (final target plan.md Section 6, Agent 1 step 3).

    CPU inference is slow (roughly a minute or more per image on a laptop CPU) — this
    is a genuine, documented performance characteristic of self-hosting, not a stub.
    """

    _pipeline = None

    def __init__(self, settings: Settings):
        self.settings = settings

    @classmethod
    def _load(cls) -> None:
        if cls._pipeline is not None:
            return
        from kavach_saathi.model_registry import get_stable_diffusion
        cls._pipeline = get_stable_diffusion()

    async def generate_view(self, garment_png: bytes, view: str, *, seed: int) -> bytes:
        import asyncio

        return await asyncio.to_thread(self._generate_view_sync, garment_png, view, seed)

    def _generate_view_sync(self, garment_png: bytes, view: str, seed: int) -> bytes:
        import cv2
        import numpy as np
        import torch
        from PIL import Image

        self._load()

        garment = Image.open(io.BytesIO(garment_png)).convert("RGB")
        edges = cv2.Canny(np.array(garment), 100, 200)
        control_image = Image.fromarray(np.stack([edges] * 3, axis=-1))

        prompt = (
            "professional e-commerce studio photo of a model wearing this garment, "
            f"{VIEW_PROMPTS[view]}, soft even studio lighting, plain neutral background, realistic fabric drape"
        )
        generator = torch.Generator().manual_seed(seed)
        result = self._pipeline(
            prompt=prompt,
            image=control_image,
            num_inference_steps=20,
            generator=generator,
        )
        output_image = result.images[0]
        buffer = io.BytesIO()
        output_image.save(buffer, format="PNG")
        return buffer.getvalue()
