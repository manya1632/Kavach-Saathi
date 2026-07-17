from __future__ import annotations

from unittest.mock import AsyncMock, patch

from conftest import poll_run
from sqlalchemy import select

from kavach_saathi.db.base import SessionLocal
from kavach_saathi.db.models import AgentLog, Product, ProductImage


def test_listing_analyze_persists_real_agent_logs_and_product_images(client, mock_spec_vision) -> None:
    """Hits the real /v1/listings/analyze endpoint through the full stack (repository,
    Postgres, agent_logs writer). The heavy model calls (SAM2/Gemini/Stable Diffusion)
    are mocked at the CatalogueImageGenerator boundary -- already proven to work for
    real in a direct end-to-end run -- so this test verifies the surrounding wiring
    (DB writes, response contract) runs in CI time instead of ~15+ CPU-minutes. The
    workflow now runs as a real background task (Agent 1 calls real models), so the
    test polls GET /v1/runs/{run_id} the same way the frontend does."""
    fake_views = [
        {
            "view": view,
            "key": f"generated/catalog/P-001-{view}.png",
            "provider": "nano_banana_2",
            "nano_banana_quota_count": 1,
            "nano_banana_daily_quota": 15,
        }
        for view in ("front", "back", "left", "right")
    ]
    target = "kavach_saathi.providers.media.CatalogueImageGenerator.generate"
    with patch(target, new=AsyncMock(return_value=fake_views)):
        response = client.post(
            "/v1/listings/analyze",
            json={
                "seller_id": "S-001",
                "product_id": "P-001",
                "image_keys": ["assets/mock/products/P-001.png"],
                "seller_specs": {
                    "fabric": "60% Cotton, 40% Viscose",
                    "gsm": 150,
                    "color_hex": "#800000",
                    "wash_care": "Gentle hand wash",
                },
            },
        )
        assert response.status_code == 200
        body = poll_run(client, response.json()["run_id"])

    catalogue_result = body["results"]["catalogue_truth"]
    assert catalogue_result["data"]["generated_views"] == fake_views

    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        assert product.stolen_photo_flag is False

        images = session.execute(
            select(ProductImage).where(ProductImage.product_id == "P-001", ProductImage.type == "ai_generated")
        ).scalars().all()
        assert {image.angle for image in images} == {"front", "back", "left", "right"}
        assert all(image.is_verified for image in images)
        assert all(image.provider == "nano_banana_2" for image in images)

        log = session.execute(
            select(AgentLog)
            .where(AgentLog.agent_name == "catalogue_truth", AgentLog.entity_id == "P-001")
            .order_by(AgentLog.id.desc())
        ).scalars().first()
        assert log is not None
        assert log.confidence == catalogue_result["confidence"]
        assert log.latency_ms >= 0
        assert log.provider == "nano_banana_2"
        assert log.output_json["generated_views"] == fake_views
