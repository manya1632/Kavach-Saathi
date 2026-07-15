from __future__ import annotations

from kavach_saathi.config import Settings

VIEW_PROMPTS = {
    "front": "front view, facing the camera directly",
    "back": "back view, showing the reverse side",
    "left": "left three-quarter angle view",
    "right": "right three-quarter angle view",
}


class NanoBananaQuotaExceeded(RuntimeError):
    pass


class NanoBananaUnavailable(RuntimeError):
    pass


class NanoBananaClient:
    """Google Gemini image generation — the model publicly nicknamed "Nano Banana"
    (`gemini-2.5-flash-image` and successors). This is the plan's "Nano Banana 2 API"
    primary catalogue image generator (final target plan.md Section 6, Agent 1).
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def _client(self):
        if not self.settings.gemini_api_key:
            raise NanoBananaUnavailable("GEMINI_API_KEY is not configured")
        from google import genai

        return genai.Client(api_key=self.settings.gemini_api_key)

    async def generate_view(self, garment_png: bytes, view: str) -> bytes:
        """Generate one professional model-shot angle from a segmented garment image."""
        import asyncio

        return await asyncio.to_thread(self._generate_view_sync, garment_png, view)

    def _generate_view_sync(self, garment_png: bytes, view: str) -> bytes:
        from google.genai import types

        client = self._client()
        prompt = (
            "Using the attached garment cutout, generate a professional e-commerce "
            f"studio photo of a model wearing this exact garment, {VIEW_PROMPTS[view]}, "
            "soft even studio lighting, plain neutral background, realistic fabric "
            "drape, do not change the garment's color, pattern, or design."
        )
        try:
            response = client.models.generate_content(
                model=self.settings.gemini_image_model,
                contents=[
                    types.Part.from_bytes(data=garment_png, mime_type="image/png"),
                    prompt,
                ],
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed quota/unavailable error below
            message = str(exc).lower()
            if "quota" in message or "resource_exhausted" in message or "429" in message:
                raise NanoBananaQuotaExceeded(str(exc)) from exc
            raise NanoBananaUnavailable(str(exc)) from exc

        for candidate in response.candidates or []:
            for part in candidate.content.parts or []:
                inline = getattr(part, "inline_data", None)
                if inline and inline.data:
                    return inline.data
        raise NanoBananaUnavailable("Gemini returned no image data")
