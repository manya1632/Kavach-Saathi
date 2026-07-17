from __future__ import annotations

import base64
import io
import time

from kavach_saathi.config import Settings
from kavach_saathi.providers.fashn_vton import BASE_MODEL_DIR, PREFIX_BY_TARGET

_BASE_URL = "https://api.fashn.ai/v1"
_POLL_INTERVAL_SECONDS = 2
_POLL_TIMEOUT_SECONDS = 60


class FashnApiUnavailable(RuntimeError):
    pass


def _data_uri(image_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(image_bytes).decode()


class FashnApiClient:
    """FASHN's own official Try-On v1.6 REST API
    (docs.fashn.ai/api-reference/tryon-v1-6) -- Agent 1's primary VTON provider.
    First-party, commercially licensed, metered pay-per-credit billing (no free-tier
    ZeroGPU ceiling or cold starts unlike `fashn_vton.py`'s free Hugging Face Space,
    which remains as a fallback if this paid tier is ever unavailable/out of
    credits). Same base model photo set and garment-flattening treatment as the
    free-Space client for identical output shape.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    async def generate_view(self, garment_png: bytes, view: str, garment_target: str, category: str) -> bytes:
        import asyncio

        return await asyncio.to_thread(self._generate_view_sync, garment_png, view, garment_target, category)

    def _generate_view_sync(self, garment_png: bytes, view: str, garment_target: str, category: str) -> bytes:
        import httpx
        from PIL import Image

        if not self.settings.fashn_api_key:
            raise FashnApiUnavailable("FASHN_API_KEY is not configured")

        prefix = PREFIX_BY_TARGET.get(garment_target)
        if prefix is None:
            raise FashnApiUnavailable(f"No base model photo set for garment_target={garment_target!r}")
        base_photo = BASE_MODEL_DIR / f"{prefix}_{view}.png"
        if not base_photo.exists():
            raise FashnApiUnavailable(f"Missing base model photo: {base_photo}")

        # Flatten the SAM2-segmented garment cutout's alpha channel onto white,
        # same treatment as the free-Space client.
        garment = Image.open(io.BytesIO(garment_png)).convert("RGBA")
        flattened = Image.new("RGB", garment.size, (255, 255, 255))
        flattened.paste(garment, mask=garment.split()[3])
        garment_buffer = io.BytesIO()
        flattened.save(garment_buffer, format="PNG")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.settings.fashn_api_key}",
        }
        payload = {
            "model_name": "tryon-v1.6",
            "inputs": {
                "model_image": _data_uri(base_photo.read_bytes()),
                "garment_image": _data_uri(garment_buffer.getvalue()),
                "category": category,
                "garment_photo_type": "flat-lay",
                "return_base64": True,
            },
        }

        try:
            with httpx.Client(timeout=30) as client:
                run_response = client.post(f"{_BASE_URL}/run", json=payload, headers=headers)
                run_response.raise_for_status()
                run_data = run_response.json()
                if run_data.get("error"):
                    raise FashnApiUnavailable(str(run_data["error"]))
                prediction_id = run_data["id"]

                deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
                while time.monotonic() < deadline:
                    time.sleep(_POLL_INTERVAL_SECONDS)
                    status_response = client.get(f"{_BASE_URL}/status/{prediction_id}", headers=headers)
                    status_response.raise_for_status()
                    status_data = status_response.json()
                    status = status_data.get("status")
                    if status == "completed":
                        output = status_data["output"][0]
                        return base64.b64decode(output.split(",", 1)[1])
                    if status not in ("starting", "in_queue", "processing"):
                        raise FashnApiUnavailable(str(status_data.get("error") or status))
                raise FashnApiUnavailable("Timed out waiting for FASHN API prediction")
        except httpx.HTTPError as exc:
            raise FashnApiUnavailable(str(exc)) from exc
