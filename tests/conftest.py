from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ["REASONING_MODE"] = "demo"
# Keep test stream consumers, idempotency keys, caches, and rate counters isolated
# from the running Compose worker on Redis DB 0. Without this, either consumer can
# legitimately claim the same test event and make mocked integration tests race.
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
# Tests must be deterministic regardless of ambient credentials. pydantic-settings reads
# .env directly (in addition to the OS environment), so a real key sitting in the repo's
# .env file -- which is exactly what a developer's local .env is expected to contain
# once they've added their own keys -- would otherwise silently switch the container's
# reasoner/vector-index from Demo/unconfigured to the real provider mid-suite. Setting
# these to an explicit empty string (not just removing the OS var) overrides the .env
# file's value, since pydantic-settings prioritizes the environment over the file.
for _key in (
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "ANTHROPIC_API_KEY",
    "PINECONE_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "BHASHINI_API_KEY",
    "RAZORPAY_KEY_ID",
    "RAZORPAY_KEY_SECRET",
    "SARVAM_API_KEY",
    "PUBLIC_BASE_URL",
    "GOOGLE_MAPS_API_KEY",
    # Added after Agent 1's provider cascade grew a FASHN/Hugging Face tier -- without
    # these, a real FASHN_API_KEY/HUGGINGFACE_API_KEY sitting in a developer's .env
    # (exactly what's expected once real keys are added) made
    # test_catalogue_generation.py's "uses nano banana"/"falls back to Stable
    # Diffusion" tests silently attempt real FASHN network calls instead of testing
    # the mocked Nano Banana/Stable Diffusion path they were named for.
    "FASHN_API_KEY",
    "HUGGINGFACE_API_KEY",
):
    os.environ[_key] = ""

from kavach_saathi.app import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def isolated_test_redis():
    from redis import Redis

    client = Redis.from_url(os.environ["REDIS_URL"])
    client.flushdb()
    yield
    client.flushdb()


@pytest.fixture(scope="session")
def client():
    # Must be a context manager, not a bare TestClient(app): Starlette only runs
    # lifespan/startup events (which start events.py's review-submitted consumer
    # thread) inside the `with` block, matching how uvicorn actually runs the app.
    with TestClient(app) as test_client:
        yield test_client


def poll_run(client: TestClient, run_id: str, *, timeout: float = 10.0) -> dict:
    """Async workflows (listing/review/return) now execute as a real background task
    (app.py's `run()` helper) instead of blocking the request, since Agents 1/2/4/8
    call real models that can take real minutes. Tests poll the same way the frontend
    does (GET /v1/runs/{run_id}) instead of asserting an immediate synchronous result.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/v1/runs/{run_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.05)
    raise TimeoutError(f"Run {run_id} did not finish within {timeout}s")


def poll_agent_log(agent_name: str, entity_id: str, *, timeout: float = 10.0):
    """Polls the real `agent_logs` table for a row written by a background event
    consumer (see events.py's review-submitted consumer thread) -- the pytest
    equivalent of poll_run for work that isn't tracked as a `RunRecord` at all.
    """
    from sqlalchemy import select

    from kavach_saathi.db.base import SessionLocal
    from kavach_saathi.db.models import AgentLog

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with SessionLocal() as session:
            log = session.execute(
                select(AgentLog)
                .where(AgentLog.agent_name == agent_name, AgentLog.entity_id == entity_id)
                .order_by(AgentLog.id.desc())
            ).scalars().first()
            if log:
                return log
        time.sleep(0.1)
    raise TimeoutError(f"No agent_logs row for {agent_name}:{entity_id} within {timeout}s")


MOCK_CATALOGUE_VIEWS = [
    {
        "view": view,
        "key": f"generated/catalog/mock-{view}.png",
        "provider": "stable_diffusion_controlnet",
        "nano_banana_quota_count": None,
        "nano_banana_daily_quota": 15,
    }
    for view in ("front", "back", "left", "right")
]


@pytest.fixture
def mock_catalogue_generation():
    """Agent 1's real image pipeline (SAM 2.0 + Nano Banana 2 / Stable Diffusion) takes
    15-70+ CPU-minutes per call -- routine tests that don't specifically exercise that
    pipeline should request this fixture rather than hit it for real. Pipeline
    correctness is covered separately by test_catalogue_generation.py (mocked
    orchestration logic) and test_catalogue_agent_integration.py (DB write path).
    """
    target = "kavach_saathi.providers.media.CatalogueImageGenerator.generate"
    with patch(target, new=AsyncMock(return_value=MOCK_CATALOGUE_VIEWS)):
        yield MOCK_CATALOGUE_VIEWS

    # save_generated_images() (repository.py) points product.media_primary at the
    # generated front view's key once it exists -- correct behavior for a real run,
    # but MOCK_CATALOGUE_VIEWS above are fake keys never actually written to disk.
    # Left as-is, media_primary stays pointed at a file that doesn't exist for the
    # rest of this session-scoped test run (the `client` fixture shares one DB across
    # the whole pytest session), breaking any later test that reads P-001's primary
    # image. Every current usage of this fixture targets P-001.
    from kavach_saathi.db.base import SessionLocal
    from kavach_saathi.db.models import Product

    with SessionLocal() as session:
        product = session.get(Product, "P-001")
        if product is not None:
            product.media_primary = "assets/mock/products/P-001.png"
            session.commit()


MOCK_CV_RESULT = {
    "clip_fabric": "cotton",
    "clip_confidence": 0.9,
    "resnet_top_labels": [{"label": "jean", "confidence": 0.5}],
    "resnet_fabric_hint": None,
    "dominant_color_hex": "#800000",
}


@pytest.fixture
def mock_spec_vision():
    """Agent 2's CLIP + ResNet-50 + SAM 2.0-backed color extraction takes ~30-60s of
    real CPU inference per call. Routine tests that don't specifically exercise that
    pipeline should request this fixture. Correctness is covered separately by
    test_spec_enforcer.py (mocked orchestration logic).
    """
    target = "kavach_saathi.providers.spec_vision.FabricVisionClassifier.classify"
    with patch(target, return_value=MOCK_CV_RESULT):
        yield MOCK_CV_RESULT
