from __future__ import annotations

import asyncio
from io import BytesIO
from unittest.mock import MagicMock, patch

from kavach_saathi.config import Settings, get_settings
from kavach_saathi.media_storage import create_presigned_upload, media_url, read_image_bytes, stored_object_size


def test_presign_returns_same_origin_path(client) -> None:
    """The presign endpoint must hand the browser a same-origin path through the
    Next.js proxy (see web/next.config.mjs's `/agent-api/:path*` rewrite) so the
    upload works regardless of what host/port the page itself was loaded from --
    no CORS, no guessing whether localhost:8000 or some other hostname is reachable
    from this particular browser."""
    response = client.post(
        "/v1/uploads/presign",
        json={"kind": "catalogue", "filename": "photo.png", "content_type": "image/png"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["upload_url"].startswith("/agent-api/v1/mock-uploads/")
    assert body["object_key"] in body["upload_url"]


def test_presign_ignores_public_base_url_for_browser_uploads(client, monkeypatch) -> None:
    """PUBLIC_BASE_URL is the Twilio webhook callback URL (a server-to-server address
    Twilio's servers must reach) and must not leak into the browser upload URL: doing
    so previously pointed browser uploads at that tunnel hostname, which fails with
    "Failed to fetch" whenever the tunnel isn't what's actually serving the page
    (e.g. testing directly against localhost)."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://kavach-demo.example.com/")
    from kavach_saathi.config import get_settings

    get_settings.cache_clear()
    try:
        response = client.post(
            "/v1/uploads/presign",
            json={"kind": "catalogue", "filename": "photo.png", "content_type": "image/png"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["upload_url"].startswith("/agent-api/v1/mock-uploads/")
        assert "kavach-demo.example.com" not in body["upload_url"]
    finally:
        get_settings.cache_clear()


def test_same_origin_upload_relay_writes_reserved_object(client) -> None:
    response = client.post(
        "/v1/uploads/presign",
        json={"kind": "delivery", "filename": "front.png", "content_type": "image/png"},
    )
    body = response.json()
    upload_path = body["upload_url"].removeprefix("/agent-api")
    written = get_settings().asset_dir / body["object_key"]
    try:
        upload = client.put(upload_path, content=b"valid-image-bytes", headers={"Content-Type": "image/png"})
        assert upload.status_code == 204, upload.text
        assert written.read_bytes() == b"valid-image-bytes"
        replay = client.put(upload_path, content=b"replay", headers={"Content-Type": "image/png"})
        assert replay.status_code == 403
    finally:
        written.unlink(missing_ok=True)


def test_object_storage_upload_uses_same_origin_relay(client) -> None:
    settings = get_settings()
    with (
        patch.object(settings, "media_storage_backend", "s3"),
        patch("kavach_saathi.app.write_generated_image") as write_object,
    ):
        response = client.post(
            "/v1/uploads/presign",
            json={"kind": "review", "filename": "review.webp", "content_type": "image/webp"},
        )
        body = response.json()
        assert body["upload_url"].startswith("/agent-api/v1/mock-uploads/")
        upload = client.put(
            body["upload_url"].removeprefix("/agent-api"),
            content=b"webp-image-bytes",
            headers={"Content-Type": "image/webp"},
        )
    assert upload.status_code == 204, upload.text
    write_object.assert_called_once_with(
        body["object_key"], b"webp-image-bytes", settings, content_type="image/webp"
    )


def test_object_storage_adapter_preserves_keys_and_signed_urls(monkeypatch) -> None:
    storage = MagicMock()
    storage.generate_presigned_url.return_value = "https://storage.example.test/signed"
    storage.head_object.return_value = {"ContentLength": 123}
    storage.get_object.return_value = {"Body": BytesIO(b"image-bytes")}
    monkeypatch.setattr("kavach_saathi.media_storage._object_client", lambda _settings: storage)
    settings = Settings(media_storage_backend="s3", media_local_read_fallback=False)

    assert create_presigned_upload("uploads/product/a.png", "image/png", settings).startswith("https://")
    assert media_url("uploads/product/a.png", settings).startswith("https://")
    assert stored_object_size("uploads/product/a.png", settings) == 123
    assert asyncio.run(read_image_bytes("uploads/product/a.png", settings)) == b"image-bytes"
    storage.head_object.assert_called_once_with(
        Bucket=settings.media_bucket,
        Key="uploads/product/a.png",
    )


def test_object_storage_public_base_url_avoids_exposing_credentials(monkeypatch) -> None:
    storage = MagicMock()
    monkeypatch.setattr("kavach_saathi.media_storage._object_client", lambda _settings: storage)
    settings = Settings(
        media_storage_backend="s3",
        media_public_base_url="https://cdn.example.test/media/",
    )

    assert media_url("uploads/product/a shirt.png", settings) == (
        "https://cdn.example.test/media/uploads/product/a%20shirt.png"
    )
    storage.generate_presigned_url.assert_not_called()
