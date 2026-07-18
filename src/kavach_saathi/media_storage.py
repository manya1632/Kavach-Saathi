from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx

from kavach_saathi.config import Settings


def _object_client(settings: Settings):
    import boto3

    kwargs = {"region_name": settings.aws_region}
    if settings.media_endpoint_url:
        kwargs["endpoint_url"] = settings.media_endpoint_url
    if settings.media_access_key_id:
        kwargs["aws_access_key_id"] = settings.media_access_key_id
    if settings.media_secret_access_key:
        kwargs["aws_secret_access_key"] = settings.media_secret_access_key
    return boto3.client("s3", **kwargs)


def _object_key(key: str, settings: Settings) -> str:
    return key.removeprefix(f"s3://{settings.media_bucket}/")


def _local_path(key: str, settings: Settings) -> Path:
    """Resolve an object key to a local file path.

    Historically the codebase used two different key conventions: full repo-relative
    paths for seeded fixtures (`assets/mock/products/P-001.png`) and plain object keys
    for freshly uploaded files (`uploads/catalogue/<uuid>.png`, written under
    `settings.asset_dir` by the mock-upload endpoint). Both need to resolve locally in
    demo mode since real model calls now actually read the bytes.
    """
    direct = Path(key)
    if direct.exists():
        return direct
    under_asset_dir = settings.asset_dir / key
    if under_asset_dir.exists():
        return under_asset_dir
    raise FileNotFoundError(f"Cannot resolve image key '{key}' to a local file")


async def read_image_bytes(key: str, settings: Settings) -> bytes:
    """Read the raw bytes for an object key, regardless of app_mode."""
    if key.startswith("http://") or key.startswith("https://"):
        async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as client:
            response = await client.get(key)
            response.raise_for_status()
            return response.content
    if settings.uses_object_storage:
        try:
            return _object_client(settings).get_object(
                Bucket=settings.media_bucket,
                Key=_object_key(key, settings),
            )["Body"].read()
        except Exception:
            if not settings.media_local_read_fallback:
                raise
            # Additive migration support: old fixture/local keys remain readable
            # while new uploads are written to object storage.
            return _local_path(key, settings).read_bytes()
    return _local_path(key, settings).read_bytes()


def write_generated_image(key: str, content: bytes, settings: Settings, *, content_type: str = "image/png") -> str:
    """Persist a generated image under `key`, returning the object key that was written."""
    if settings.uses_object_storage:
        _object_client(settings).put_object(
            Bucket=settings.media_bucket, Key=key, Body=content, ContentType=content_type
        )
        return key
    destination = settings.asset_dir / key
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return key


def create_presigned_upload(key: str, content_type: str, settings: Settings) -> str:
    return _object_client(settings).generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.media_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=settings.media_presign_expiry_seconds,
    )


def stored_object_size(key: str, settings: Settings) -> int:
    if settings.uses_object_storage:
        try:
            head = _object_client(settings).head_object(
                Bucket=settings.media_bucket,
                Key=_object_key(key, settings),
            )
            return int(head.get("ContentLength", 0))
        except Exception:
            if not settings.media_local_read_fallback:
                raise
    return _local_path(key, settings).stat().st_size


def media_url(key: str | None, settings: Settings, *, expires_in: int = 3600) -> str | None:
    if not key:
        return None
    if key.startswith("http://") or key.startswith("https://"):
        return key
    normalized = _object_key(key, settings)
    if settings.uses_object_storage:
        if settings.media_public_base_url:
            return f"{settings.media_public_base_url.rstrip('/')}/{quote(normalized, safe='/')}"
        return _object_client(settings).generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.media_bucket, "Key": normalized},
            ExpiresIn=expires_in,
        )
    return f"/mock-assets/{normalized.removeprefix('assets/mock/')}"
