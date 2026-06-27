import hashlib
import json
from typing import Any

from app.cache.redis_client import get_redis


def cache_key_for_ai(provider: str, model: str, messages: list[dict], extra: dict | None = None) -> str:
    raw = json.dumps(
        {"provider": provider, "model": model, "messages": messages, "extra": extra or {}},
        sort_keys=True,
    )
    return "ai:response:" + hashlib.sha256(raw.encode()).hexdigest()


async def get_cached_ai(key: str) -> dict[str, Any] | None:
    raw = await get_redis().get(key)
    return json.loads(raw) if raw else None


async def set_cached_ai(key: str, value: dict[str, Any], ttl_seconds: int = 600) -> None:
    await get_redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)
