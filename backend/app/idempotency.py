from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import Request, Response

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
TTL_SECONDS = 3600


@dataclass
class CachedResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes
    expires_at: float


_cache: dict[str, CachedResponse] = {}


def _cache_key(request: Request, key: str) -> str:
    user = getattr(request.state, "user_id", None)
    return f"{user or 'anonymous'}:{request.method}:{request.url.path}:{key}"


async def idempotency_middleware(request: Request, call_next):
    key = request.headers.get("idempotency-key")
    if request.method.upper() not in MUTATION_METHODS or not key:
        return await call_next(request)

    now = time.monotonic()
    for cache_key, cached in list(_cache.items()):
        if cached.expires_at <= now:
            _cache.pop(cache_key, None)

    cache_key = _cache_key(request, key)
    cached = _cache.get(cache_key)
    if cached is not None and cached.expires_at > now:
        headers = dict(cached.headers)
        headers["Idempotency-Replayed"] = "true"
        return Response(content=cached.body, status_code=cached.status_code, headers=headers)

    response = await call_next(request)
    if response.status_code < 200 or response.status_code >= 300:
        return response
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    headers = dict(response.headers)
    headers["Idempotency-Replayed"] = "false"
    _cache[cache_key] = CachedResponse(response.status_code, headers, body, time.monotonic() + TTL_SECONDS)
    return Response(content=body, status_code=response.status_code, headers=headers, media_type=response.media_type)
