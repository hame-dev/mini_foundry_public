"""Operations console: read-only introspection of workers, queues, caches,
storage, metrics, and logs.

All endpoints are admin-guarded and reuse existing infrastructure (Celery
control, the async Redis client, the storage filesystem, and the audit/usage
tables). Nothing here mutates state except the explicit cache-flush endpoint.
Endpoints degrade gracefully (empty / not-configured) when the underlying
infrastructure is idle, so the console never 500s on a quiet system.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import anyio
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.cache.redis_client import get_redis
from app.config import get_settings, production_hardening_issues
from app.deps import AdminDep, SessionDep
from app.governance.models import UsageMetric
from app.jobs.celery_app import celery_app
from app.storage.fs import default_bucket_uri, get_fs

router = APIRouter(prefix="/operations", tags=["operations"])

# Known Redis cache namespaces (see app/cache and app/dashboards/cache.py).
CACHE_NAMESPACES = ["sql:result:", "ai:response:", "dashboard:component:"]
# Default Celery queue name (no custom task_routes configured).
DEFAULT_QUEUES = ["celery"]
# Bound on how many objects we walk when summarizing storage / scanning keys.
SCAN_LIMIT = 10_000


# --------------------------------------------------------------------- workers


class WorkerOut(BaseModel):
    name: str
    status: str
    active_task_count: int
    pool: str | None = None


class WorkersOut(BaseModel):
    configured: bool
    workers: list[WorkerOut]


def _inspect_workers() -> WorkersOut:
    """Blocking Celery control inspect; call via anyio.to_thread.run_sync."""
    inspect = celery_app.control.inspect(timeout=1.0)
    ping = inspect.ping() or {}
    if not ping:
        return WorkersOut(configured=False, workers=[])
    active = inspect.active() or {}
    stats = inspect.stats() or {}
    workers: list[WorkerOut] = []
    for name in sorted(ping):
        worker_stats = stats.get(name) or {}
        pool = (worker_stats.get("pool") or {}).get("implementation")
        workers.append(
            WorkerOut(
                name=name,
                status="online",
                active_task_count=len(active.get(name) or []),
                pool=pool,
            )
        )
    return WorkersOut(configured=True, workers=workers)


@router.get("/workers", response_model=WorkersOut)
async def list_workers(_: AdminDep) -> WorkersOut:
    try:
        return await anyio.to_thread.run_sync(_inspect_workers)
    except Exception:
        # Broker unreachable / no workers — report not configured rather than 500.
        return WorkersOut(configured=False, workers=[])


# ---------------------------------------------------------------------- queues


class QueueOut(BaseModel):
    name: str
    depth: int


class QueuesOut(BaseModel):
    queues: list[QueueOut]


@router.get("/queues", response_model=QueuesOut)
async def list_queues(_: AdminDep) -> QueuesOut:
    redis = get_redis()
    queues: list[QueueOut] = []
    for name in DEFAULT_QUEUES:
        try:
            depth = await redis.llen(name)
        except Exception:
            depth = 0
        queues.append(QueueOut(name=name, depth=int(depth or 0)))
    return QueuesOut(queues=queues)


# ---------------------------------------------------------------------- caches


class CacheNamespaceOut(BaseModel):
    prefix: str
    key_count: int


class CachesOut(BaseModel):
    used_memory: int | None = None
    used_memory_human: str | None = None
    total_keys: int | None = None
    namespaces: list[CacheNamespaceOut]


async def _count_prefix(redis, prefix: str) -> int:
    count = 0
    async for _ in redis.scan_iter(match=f"{prefix}*", count=500):
        count += 1
        if count >= SCAN_LIMIT:
            break
    return count


@router.get("/caches", response_model=CachesOut)
async def inspect_caches(_: AdminDep) -> CachesOut:
    redis = get_redis()
    used_memory: int | None = None
    used_memory_human: str | None = None
    total_keys: int | None = None
    try:
        info = await redis.info("memory")
        used_memory = info.get("used_memory")
        used_memory_human = info.get("used_memory_human")
    except Exception:
        pass
    try:
        total_keys = await redis.dbsize()
    except Exception:
        pass
    namespaces: list[CacheNamespaceOut] = []
    for prefix in CACHE_NAMESPACES:
        try:
            namespaces.append(CacheNamespaceOut(prefix=prefix, key_count=await _count_prefix(redis, prefix)))
        except Exception:
            namespaces.append(CacheNamespaceOut(prefix=prefix, key_count=0))
    return CachesOut(
        used_memory=used_memory,
        used_memory_human=used_memory_human,
        total_keys=total_keys,
        namespaces=namespaces,
    )


class FlushOut(BaseModel):
    prefix: str
    deleted: int


@router.post("/caches/flush", response_model=FlushOut)
async def flush_cache(_: AdminDep, prefix: str = Query(..., description="Cache key prefix to flush")) -> FlushOut:
    if prefix not in CACHE_NAMESPACES:
        # Only allow flushing known namespaces.
        return FlushOut(prefix=prefix, deleted=0)
    redis = get_redis()
    deleted = 0
    keys: list[str] = []
    async for key in redis.scan_iter(match=f"{prefix}*", count=500):
        keys.append(key)
        if len(keys) >= 500:
            deleted += await redis.delete(*keys)
            keys = []
        if deleted >= SCAN_LIMIT:
            break
    if keys:
        deleted += await redis.delete(*keys)
    return FlushOut(prefix=prefix, deleted=int(deleted))


# --------------------------------------------------------------------- storage


class StorageOut(BaseModel):
    backend: str
    location: str
    reachable: bool
    object_count: int | None = None
    total_bytes: int | None = None
    detail: str | None = None


def _inspect_storage() -> StorageOut:
    settings = get_settings()
    base_uri = default_bucket_uri("")
    backend = settings.storage_backend
    location = settings.s3_bucket if backend == "s3" else settings.local_storage_path
    try:
        fs = get_fs(base_uri if backend == "s3" else None)
        root = base_uri if backend == "s3" else settings.local_storage_path
        object_count = 0
        total_bytes = 0
        for info in fs.find(root, detail=True, maxdepth=None).values():
            object_count += 1
            total_bytes += int(info.get("size") or 0)
            if object_count >= SCAN_LIMIT:
                break
        return StorageOut(
            backend=backend,
            location=location,
            reachable=True,
            object_count=object_count,
            total_bytes=total_bytes,
        )
    except Exception as e:
        return StorageOut(backend=backend, location=location, reachable=False, detail=str(e))


@router.get("/storage", response_model=StorageOut)
async def inspect_storage(_: AdminDep) -> StorageOut:
    return await anyio.to_thread.run_sync(_inspect_storage)


# --------------------------------------------------------------------- metrics


class EventCountOut(BaseModel):
    event_type: str
    count: int


class LatencyOut(BaseModel):
    resource_type: str
    count: int
    avg_ms: float
    max_ms: int


class MetricsOut(BaseModel):
    window_hours: int
    total_events: int
    error_events: int
    event_counts: list[EventCountOut]
    latency: list[LatencyOut]


@router.get("/metrics", response_model=MetricsOut)
async def operations_metrics(session: SessionDep, _: AdminDep, window_hours: int = 24) -> MetricsOut:
    since = datetime.utcnow() - timedelta(hours=window_hours)

    counts_rows = (
        await session.execute(
            select(AuditLog.event_type, func.count())
            .where(AuditLog.created_at >= since)
            .group_by(AuditLog.event_type)
            .order_by(func.count().desc())
        )
    ).all()
    event_counts = [EventCountOut(event_type=et, count=int(c)) for et, c in counts_rows]
    total_events = sum(e.count for e in event_counts)
    error_events = sum(e.count for e in event_counts if "FAIL" in e.event_type.upper() or "DENIED" in e.event_type.upper())

    latency_rows = (
        await session.execute(
            select(
                UsageMetric.resource_type,
                func.count(),
                func.avg(UsageMetric.execution_time_ms),
                func.max(UsageMetric.execution_time_ms),
            )
            .where(UsageMetric.created_at >= since)
            .group_by(UsageMetric.resource_type)
            .order_by(func.avg(UsageMetric.execution_time_ms).desc())
        )
    ).all()
    latency = [
        LatencyOut(resource_type=rt, count=int(c), avg_ms=float(avg or 0), max_ms=int(mx or 0))
        for rt, c, avg, mx in latency_rows
    ]

    return MetricsOut(
        window_hours=window_hours,
        total_events=total_events,
        error_events=error_events,
        event_counts=event_counts,
        latency=latency,
    )


# ------------------------------------------------------------------ hardening


class HardeningOut(BaseModel):
    environment: str
    enforced: bool
    status: str
    issues: list[str]
    bearer_auth_enabled: bool
    backup_restore_verified: bool
    metrics_alerting_configured: bool
    rootless_sandbox_host: bool


@router.get("/hardening", response_model=HardeningOut)
async def hardening_status(_: AdminDep) -> HardeningOut:
    settings = get_settings()
    issues = production_hardening_issues(settings)
    return HardeningOut(
        environment=settings.environment,
        enforced=settings.environment == "production" and settings.require_production_hardening,
        status="ok" if not issues else "blocked",
        issues=issues,
        bearer_auth_enabled=bool(settings.allow_bearer_auth),
        backup_restore_verified=settings.backup_restore_verified,
        metrics_alerting_configured=settings.metrics_alerting_configured,
        rootless_sandbox_host=settings.rootless_sandbox_host,
    )


# ------------------------------------------------------------------------ logs


class LogOut(BaseModel):
    id: str
    user_id: str | None
    event_type: str
    resource_type: str | None
    resource_id: str | None
    provider: str | None
    input_summary: dict | None
    output_summary: dict | None
    created_at: datetime


@router.get("/logs", response_model=list[LogOut])
async def query_logs(
    session: SessionDep,
    _: AdminDep,
    event_type: str | None = None,
    resource_type: str | None = None,
    since: datetime | None = None,
    limit: int = Query(200, le=1000),
) -> list[LogOut]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if since:
        stmt = stmt.where(AuditLog.created_at >= since)
    stmt = stmt.limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        LogOut(
            id=str(r.id),
            user_id=str(r.user_id) if r.user_id else None,
            event_type=r.event_type,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            provider=r.provider,
            input_summary=r.input_summary,
            output_summary=r.output_summary,
            created_at=r.created_at,
        )
        for r in rows
    ]
