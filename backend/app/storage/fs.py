"""fsspec wrapper. `s3://` URIs route to MinIO; `file://` and bare paths
hit the local filesystem.
"""
from __future__ import annotations

import fsspec

from app.config import get_settings


def get_fs(uri: str | None = None) -> fsspec.AbstractFileSystem:
    """Return an fsspec filesystem appropriate for the URI scheme.
    If URI is None or has no scheme, fall back to the configured backend.
    """
    settings = get_settings()
    if uri and uri.startswith("s3://"):
        return _s3_fs()
    if uri and uri.startswith(("file://", "/")):
        return fsspec.filesystem("file")
    # No scheme — pick default
    if settings.storage_backend == "s3":
        return _s3_fs()
    return fsspec.filesystem("file")


def _s3_fs() -> fsspec.AbstractFileSystem:
    settings = get_settings()
    return fsspec.filesystem(
        "s3",
        key=settings.s3_access_key,
        secret=settings.s3_secret_key,
        client_kwargs={"endpoint_url": settings.s3_endpoint},
    )


def default_bucket_uri(path: str) -> str:
    """Build a canonical URI for a path inside the default bucket."""
    settings = get_settings()
    if settings.storage_backend == "s3":
        return f"s3://{settings.s3_bucket}/{path.lstrip('/')}"
    return f"{settings.local_storage_path.rstrip('/')}/{path.lstrip('/')}"
