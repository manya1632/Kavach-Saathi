from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from kavach_saathi.config import Settings
from kavach_saathi.providers.catalogue_generation import CatalogueImageGenerator
from kavach_saathi.providers.nano_banana import NanoBananaQuotaExceeded


def _settings(**overrides) -> Settings:
    base = {"database_url": "postgresql+psycopg://kavach:kavach@localhost:5432/kavach_saathi"}
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def fake_source_bytes():
    target = "kavach_saathi.providers.catalogue_generation.read_image_bytes"
    with patch(target, new=AsyncMock(return_value=b"fake-bytes")):
        yield


@pytest.fixture
def fake_write():
    target = "kavach_saathi.providers.catalogue_generation.write_generated_image"
    with patch(target, return_value="generated/catalog/x.png"):
        yield


@pytest.mark.usefixtures("fake_source_bytes", "fake_write")
def test_routes_to_stable_diffusion_when_gemini_not_configured():
    settings = _settings(gemini_api_key=None)
    generator = CatalogueImageGenerator(settings)

    with (
        patch.object(generator.segmenter, "segment", return_value=b"segmented"),
        patch.object(generator.nano_banana, "generate_view", new=AsyncMock(return_value=b"nb-image")) as nb_mock,
        patch.object(generator.sd_fallback, "generate_view", new=AsyncMock(return_value=b"sd-image")) as sd_mock,
    ):
        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            generator.generate(["some/key.png"], {"id": "P-TEST"})
        )

    assert len(results) == 4
    assert all(r["provider"] == "stable_diffusion_controlnet" for r in results)
    nb_mock.assert_not_called()
    assert sd_mock.call_count == 4


@pytest.mark.usefixtures("fake_source_bytes", "fake_write")
def test_uses_nano_banana_when_configured_and_within_quota():
    settings = _settings(gemini_api_key="fake-key", nano_banana_daily_quota=15)
    generator = CatalogueImageGenerator(settings)

    with (
        patch.object(generator.segmenter, "segment", return_value=b"segmented"),
        patch.object(generator.nano_banana, "generate_view", new=AsyncMock(return_value=b"nb-image")) as nb_mock,
        patch.object(generator.sd_fallback, "generate_view", new=AsyncMock(return_value=b"sd-image")) as sd_mock,
        patch(
            "kavach_saathi.providers.catalogue_generation.increment_and_check_quota",
            return_value=(1, True),
        ),
    ):
        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            generator.generate(["some/key.png"], {"id": "P-TEST"})
        )

    assert all(r["provider"] == "nano_banana_2" for r in results)
    assert nb_mock.call_count == 4
    sd_mock.assert_not_called()


@pytest.mark.usefixtures("fake_source_bytes", "fake_write")
def test_falls_back_to_stable_diffusion_when_quota_exceeded():
    settings = _settings(gemini_api_key="fake-key", nano_banana_daily_quota=15)
    generator = CatalogueImageGenerator(settings)

    with (
        patch.object(generator.segmenter, "segment", return_value=b"segmented"),
        patch.object(generator.nano_banana, "generate_view", new=AsyncMock(return_value=b"nb-image")) as nb_mock,
        patch.object(generator.sd_fallback, "generate_view", new=AsyncMock(return_value=b"sd-image")) as sd_mock,
        patch(
            "kavach_saathi.providers.catalogue_generation.increment_and_check_quota",
            return_value=(16, False),
        ),
    ):
        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            generator.generate(["some/key.png"], {"id": "P-TEST"})
        )

    assert all(r["provider"] == "stable_diffusion_controlnet" for r in results)
    nb_mock.assert_not_called()
    assert sd_mock.call_count == 4


@pytest.mark.usefixtures("fake_source_bytes", "fake_write")
def test_falls_back_to_stable_diffusion_when_nano_banana_errors():
    settings = _settings(gemini_api_key="fake-key", nano_banana_daily_quota=15)
    generator = CatalogueImageGenerator(settings)

    with (
        patch.object(generator.segmenter, "segment", return_value=b"segmented"),
        patch.object(
            generator.nano_banana,
            "generate_view",
            new=AsyncMock(side_effect=NanoBananaQuotaExceeded("429")),
        ) as nb_mock,
        patch.object(generator.sd_fallback, "generate_view", new=AsyncMock(return_value=b"sd-image")) as sd_mock,
        patch(
            "kavach_saathi.providers.catalogue_generation.increment_and_check_quota",
            return_value=(1, True),
        ),
    ):
        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            generator.generate(["some/key.png"], {"id": "P-TEST"})
        )

    assert all(r["provider"] == "stable_diffusion_controlnet" for r in results)
    assert nb_mock.call_count == 4
    assert sd_mock.call_count == 4
