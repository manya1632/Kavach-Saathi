from __future__ import annotations


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
