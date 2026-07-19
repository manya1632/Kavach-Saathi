from __future__ import annotations

import asyncio
import base64
import builtins
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kavach_saathi.config import Settings
from kavach_saathi.providers.fashn_api import FashnApiClient
from kavach_saathi.providers.fashn_vton import FashnVtonClient, FashnVtonUnavailable
from kavach_saathi.providers.image_quality import ImageQualityAssessor
from kavach_saathi.providers.stolen_photo import GoogleVisionReverseImageSearch, GoogleVisionUnavailable

_SAMPLE_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "mock" / "products" / "P-001.png"


def test_all_fashn_base_model_photos_are_bundled() -> None:
    base_dir = Path(__file__).resolve().parent.parent / "assets" / "model_base"
    expected = {f"{prefix}_{view}.png" for prefix in "bfmg" for view in ("front", "back", "left", "right")}
    assert {path.name for path in base_dir.glob("*.png")} == expected


def test_paid_fashn_request_and_polling_contract_without_spending_credits(monkeypatch) -> None:
    generated = b"generated-image-bytes"
    run_response = MagicMock()
    run_response.raise_for_status = MagicMock()
    run_response.json.return_value = {"id": "prediction-1", "error": None}
    queued_response = MagicMock()
    queued_response.raise_for_status = MagicMock()
    queued_response.json.return_value = {"id": "prediction-1", "status": "processing", "error": None}
    complete_response = MagicMock()
    complete_response.raise_for_status = MagicMock()
    complete_response.json.return_value = {
        "id": "prediction-1",
        "status": "completed",
        "output": ["data:image/png;base64," + base64.b64encode(generated).decode("ascii")],
        "error": None,
    }

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    fake_client.post.return_value = run_response
    fake_client.get.side_effect = [queued_response, complete_response]
    monkeypatch.setattr("httpx.Client", lambda **_kwargs: fake_client)
    monkeypatch.setattr("kavach_saathi.providers.fashn_api.time.sleep", lambda _seconds: None)

    result = FashnApiClient(Settings(fashn_api_key="test-key"))._generate_view_sync(
        _SAMPLE_IMAGE.read_bytes(), "front", "woman", "one-pieces"
    )

    assert result == generated
    request_payload = fake_client.post.call_args.kwargs["json"]
    assert request_payload["model_name"] == "tryon-v1.6"
    assert request_payload["inputs"]["category"] == "one-pieces"
    assert request_payload["inputs"]["garment_photo_type"] == "flat-lay"
    assert request_payload["inputs"]["return_base64"] is True
    assert fake_client.get.call_count == 2


def test_image_quality_assessor_scores_a_real_photo() -> None:
    """Real OpenCV computation against a real product photo -- replaces the previous
    hardcoded quality=0.9 constant that never looked at the actual image."""
    assessor = ImageQualityAssessor()
    result = assessor.assess(_SAMPLE_IMAGE.read_bytes())
    assert 0.0 <= result["quality"] <= 1.0
    assert result["width"] > 0
    assert result["height"] > 0
    assert result["blur_variance"] >= 0.0


def test_image_quality_assessor_handles_undecodable_bytes() -> None:
    assessor = ImageQualityAssessor()
    result = assessor.assess(b"not a real image")
    assert result["quality"] == 0.0
    assert result["width"] == 0


def test_stolen_photo_search_raises_when_unconfigured() -> None:
    settings = Settings(google_vision_api_key=None)
    provider = GoogleVisionReverseImageSearch(settings)
    assert provider.is_configured is False

    with pytest.raises(GoogleVisionUnavailable):
        asyncio.run(provider.search(b"fake-bytes"))


def test_stolen_photo_search_parses_real_rest_response_shape() -> None:
    """The REST endpoint returns camelCase keys (fullMatchingImages, etc.) -- this
    verifies the parsing logic against that real response shape, not the old
    client library's snake_case attributes."""
    settings = Settings(google_vision_api_key="test-key")
    provider = GoogleVisionReverseImageSearch(settings)

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "responses": [
            {
                "webDetection": {
                    "fullMatchingImages": [{"url": "https://example.com/full.jpg"}],
                    "partialMatchingImages": [{"url": "https://example.com/partial.jpg"}],
                    "pagesWithMatchingImages": [{"url": "https://example.com/page"}],
                }
            }
        ]
    }

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__aenter__.return_value
        mock_client.post = AsyncMock(return_value=fake_response)

        result = asyncio.run(provider.search(b"fake-bytes"))

    assert result == {
        "full_matches": ["https://example.com/full.jpg"],
        "partial_matches": ["https://example.com/partial.jpg"],
        "pages": ["https://example.com/page"],
    }


def test_missing_gradio_client_is_a_typed_provider_fallback(tmp_path, monkeypatch) -> None:
    base_dir = tmp_path / "model_base"
    base_dir.mkdir()
    (base_dir / "f_front.png").write_bytes(_SAMPLE_IMAGE.read_bytes())
    monkeypatch.setattr("kavach_saathi.providers.fashn_vton.BASE_MODEL_DIR", base_dir)

    real_import = builtins.__import__

    def import_without_gradio(name, *args, **kwargs):
        if name.startswith("gradio_client"):
            raise ModuleNotFoundError("No module named 'gradio_client'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_gradio)
    provider = FashnVtonClient(Settings(huggingface_api_key="configured"))

    with pytest.raises(FashnVtonUnavailable, match="gradio_client"):
        provider._generate_view_sync(_SAMPLE_IMAGE.read_bytes(), "front", "woman", "tops")
