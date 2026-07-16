from __future__ import annotations

import io

from kavach_saathi.config import Settings
from kavach_saathi.providers.nano_banana import VIEW_PROMPTS


class HuggingFaceImageUnavailable(RuntimeError):
    pass


class HuggingFaceImageClient:
    """Hugging Face Inference API image-to-image generation -- Agent 1's fast fallback
    when Nano Banana 2's quota is exhausted. Runs on HF's own GPU-backed Inference
    Providers (FLUX.1 Kontext), not local CPU, so a full set of 4 views takes roughly
    30-40 seconds total instead of the 4-8+ minutes a self-hosted Stable Diffusion
    CPU pipeline needs. Falls back to the local Stable Diffusion pipeline if this is
    also unavailable (no token, rate-limited, or a genuine outage)."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def _client(self):
        if not self.settings.huggingface_api_key:
            raise HuggingFaceImageUnavailable("HUGGINGFACE_API_KEY is not configured")
        from huggingface_hub import InferenceClient

        return InferenceClient(token=self.settings.huggingface_api_key)

    async def generate_view(self, garment_png: bytes, view: str) -> bytes:
        import asyncio

        return await asyncio.to_thread(self._generate_view_sync, garment_png, view)

    def _generate_view_sync(self, garment_png: bytes, view: str) -> bytes:
        from PIL import Image

        client = self._client()
        garment = Image.open(io.BytesIO(garment_png)).convert("RGB")
        prompt = (
            "Professional e-commerce studio photo of a model wearing this exact "
            f"garment, {VIEW_PROMPTS[view]}, soft even studio lighting, plain neutral "
            "background, realistic fabric drape, do not change the garment's color, "
            "pattern, or design."
        )
        try:
            output = client.image_to_image(garment, prompt=prompt, model=self.settings.huggingface_image_model)
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed unavailable error below
            raise HuggingFaceImageUnavailable(str(exc)) from exc

        buffer = io.BytesIO()
        output.save(buffer, format="PNG")
        return buffer.getvalue()
