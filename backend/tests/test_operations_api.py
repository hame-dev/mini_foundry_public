import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.operations import router as ops


# --------------------------------------------------------------------- workers

@pytest.mark.asyncio
async def test_workers_not_configured_when_no_ping():
    inspect = MagicMock()
    inspect.ping.return_value = {}
    with patch.object(ops.celery_app.control, "inspect", return_value=inspect):
        result = await ops.list_workers(_=MagicMock())
    assert result.configured is False
    assert result.workers == []


@pytest.mark.asyncio
async def test_workers_reports_active_counts():
    inspect = MagicMock()
    inspect.ping.return_value = {"w1": {"ok": "pong"}}
    inspect.active.return_value = {"w1": [{"id": "t1"}, {"id": "t2"}]}
    inspect.stats.return_value = {"w1": {"pool": {"implementation": "prefork"}}}
    with patch.object(ops.celery_app.control, "inspect", return_value=inspect):
        result = await ops.list_workers(_=MagicMock())
    assert result.configured is True
    assert result.workers[0].name == "w1"
    assert result.workers[0].active_task_count == 2
    assert result.workers[0].pool == "prefork"


@pytest.mark.asyncio
async def test_workers_degrades_on_broker_error():
    with patch.object(ops.celery_app.control, "inspect", side_effect=RuntimeError("no broker")):
        result = await ops.list_workers(_=MagicMock())
    assert result.configured is False


# ---------------------------------------------------------------------- queues

@pytest.mark.asyncio
async def test_queues_returns_depth():
    redis = MagicMock()
    redis.llen = AsyncMock(return_value=3)
    with patch.object(ops, "get_redis", return_value=redis):
        result = await ops.list_queues(_=MagicMock())
    assert result.queues[0].name == "celery"
    assert result.queues[0].depth == 3


@pytest.mark.asyncio
async def test_queues_degrades_on_redis_error():
    redis = MagicMock()
    redis.llen = AsyncMock(side_effect=RuntimeError("down"))
    with patch.object(ops, "get_redis", return_value=redis):
        result = await ops.list_queues(_=MagicMock())
    assert result.queues[0].depth == 0


# ---------------------------------------------------------------------- caches

class _FakeScan:
    """Async-iterable stand-in for redis.scan_iter."""

    def __init__(self, keys):
        self._keys = keys

    def __call__(self, *args, **kwargs):
        async def gen():
            for k in self._keys:
                yield k

        return gen()


@pytest.mark.asyncio
async def test_caches_counts_namespaces():
    redis = MagicMock()
    redis.info = AsyncMock(return_value={"used_memory": 1024, "used_memory_human": "1K"})
    redis.dbsize = AsyncMock(return_value=5)
    redis.scan_iter = _FakeScan(["a", "b"])
    with patch.object(ops, "get_redis", return_value=redis):
        result = await ops.inspect_caches(_=MagicMock())
    assert result.used_memory == 1024
    assert result.total_keys == 5
    assert all(ns.key_count == 2 for ns in result.namespaces)


@pytest.mark.asyncio
async def test_cache_flush_rejects_unknown_prefix():
    result = await ops.flush_cache(_=MagicMock(), prefix="evil:")
    assert result.deleted == 0


# --------------------------------------------------------------------- storage

@pytest.mark.asyncio
async def test_storage_summarizes_objects():
    fs = MagicMock()
    fs.find.return_value = {"a": {"size": 100}, "b": {"size": 200}}
    with patch.object(ops, "get_fs", return_value=fs):
        result = await ops.inspect_storage(_=MagicMock())
    assert result.reachable is True
    assert result.object_count == 2
    assert result.total_bytes == 300


@pytest.mark.asyncio
async def test_storage_unreachable_on_error():
    with patch.object(ops, "get_fs", side_effect=RuntimeError("no bucket")):
        result = await ops.inspect_storage(_=MagicMock())
    assert result.reachable is False
    assert result.detail


# --------------------------------------------------------------------- metrics

@pytest.mark.asyncio
async def test_metrics_aggregates_events_and_latency():
    session = AsyncMock()
    counts = MagicMock()
    counts.all.return_value = [("SQL_RUN", 4), ("AUTHORIZATION_DENIED", 1)]
    latency = MagicMock()
    latency.all.return_value = [("ai_sql", 2, 150.0, 300)]
    session.execute.side_effect = [counts, latency]
    result = await ops.operations_metrics(session=session, _=MagicMock(), window_hours=24)
    assert result.total_events == 5
    assert result.error_events == 1
    assert result.latency[0].avg_ms == 150.0


# ------------------------------------------------------------------------ logs

@pytest.mark.asyncio
async def test_logs_returns_entries():
    session = AsyncMock()
    row = MagicMock()
    row.id = uuid.uuid4()
    row.user_id = None
    row.event_type = "SQL_RUN"
    row.resource_type = "dataset"
    row.resource_id = "abc"
    row.provider = None
    row.input_summary = {}
    row.output_summary = None
    import datetime as dt

    row.created_at = dt.datetime.utcnow()
    res = MagicMock()
    res.scalars.return_value.all.return_value = [row]
    session.execute.return_value = res
    result = await ops.query_logs(session=session, _=MagicMock(), limit=200)
    assert result[0].event_type == "SQL_RUN"


# ------------------------------------------------------------------ hardening

@pytest.mark.asyncio
async def test_hardening_reports_production_issues():
    from app.config import Settings

    settings = Settings(environment="production")
    with patch.object(ops, "get_settings", return_value=settings), patch.object(ops, "production_hardening_issues", return_value=["jwt_secret must be replaced"]):
        result = await ops.hardening_status(_=MagicMock())
    assert result.status == "blocked"
    assert result.enforced is True
    assert result.issues == ["jwt_secret must be replaced"]
