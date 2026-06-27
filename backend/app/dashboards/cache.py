import hashlib
import json
import uuid
from typing import Any

from app.cache.redis_client import get_redis


def render_cache_key(
    *,
    user_id: uuid.UUID,
    dashboard_id: uuid.UUID,
    component_id: uuid.UUID,
    binding: dict[str, Any] | None,
    filters: dict[str, Any] | None,
    permission_version: int,
    cache_context: dict[str, Any] | None = None,
) -> str:
    raw = json.dumps(
        {
            "user_id": str(user_id),
            "dashboard_id": str(dashboard_id),
            "component_id": str(component_id),
            "binding": binding or {},
            "filters": filters or {},
            "permission_version": permission_version,
            "cache_context": cache_context or {},
        },
        sort_keys=True,
        default=str,
    )
    return f"dashboard:component:{component_id}:result:" + hashlib.sha256(raw.encode()).hexdigest()


async def get_cached_render(key: str) -> dict[str, Any] | None:
    raw = await get_redis().get(key)
    return json.loads(raw) if raw else None


async def set_cached_render(key: str, value: dict[str, Any], ttl_seconds: int = 300) -> None:
    await get_redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)
