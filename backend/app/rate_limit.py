from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Request, Response
from fastapi.responses import JSONResponse


@dataclass(frozen=True)
class LimitRule:
    requests: int
    window_seconds: int


DEFAULT_RULE = LimitRule(600, 60)
AUTH_RULE = LimitRule(30, 60)
EXPENSIVE_RULE = LimitRule(60, 60)

_buckets: dict[str, deque[float]] = defaultdict(deque)


def _rule_for(path: str) -> LimitRule:
    if "/auth/login" in path or "/auth/register" in path or "/password-reset" in path:
        return AUTH_RULE
    if "/ai/run-sql" in path or "/ai/sql" in path or "/queries/" in path or "/logic/run" in path:
        return EXPENSIVE_RULE
    return DEFAULT_RULE


def _key(request: Request) -> str:
    user = getattr(request.state, "user_id", None)
    ip = request.client.host if request.client else "unknown"
    return f"{user or ip}:{request.url.path}"


async def rate_limit_middleware(request: Request, call_next):
    rule = _rule_for(request.url.path)
    now = time.monotonic()
    key = _key(request)
    bucket = _buckets[key]
    while bucket and bucket[0] <= now - rule.window_seconds:
        bucket.popleft()
    remaining = max(0, rule.requests - len(bucket))
    if remaining <= 0:
        reset = int(rule.window_seconds - (now - bucket[0])) if bucket else rule.window_seconds
        return JSONResponse(
            {"detail": "rate limit exceeded"},
            status_code=429,
            headers={
                "X-RateLimit-Limit": str(rule.requests),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(max(1, reset)),
            },
        )
    bucket.append(now)
    response: Response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(rule.requests)
    response.headers["X-RateLimit-Remaining"] = str(max(0, remaining - 1))
    response.headers["X-RateLimit-Reset"] = str(rule.window_seconds)
    return response
