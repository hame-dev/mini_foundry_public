import hashlib
import json
from typing import Any

from app.cache.redis_client import get_redis


def cache_key_for_sql(
    user_id: str,
    sql: str,
    permission_version: int,
    *,
    dataset_version_ids: list[str] | None = None,
    branch_id: str | None = None,
    engine: str | None = None,
    row_policy_version: int | None = None,
    mask_policy_version: int | None = None,
) -> str:
    raw = json.dumps(
        {
            "user_id": user_id,
            "sql": sql,
            "permission_version": permission_version,
            "dataset_version_ids": dataset_version_ids or [],
            "branch_id": branch_id or "main",
            "engine": engine or "auto",
            "row_policy_version": row_policy_version or permission_version,
            "mask_policy_version": mask_policy_version or permission_version,
        },
        sort_keys=True,
    )
    return "sql:result:" + hashlib.sha256(raw.encode()).hexdigest()


async def get_cached_result(key: str) -> dict[str, Any] | None:
    raw = await get_redis().get(key)
    return json.loads(raw) if raw else None


async def set_cached_result(key: str, value: dict[str, Any], ttl_seconds: int = 300) -> None:
    await get_redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)
