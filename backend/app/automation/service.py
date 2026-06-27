from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.automation.models import AutomationMonitor, AutomationMonitorRun
from app.data.models import Dataset
from app.governed_query.service import governed_query
from app.notifications.service import create_notification
from app.platform.models import BuildRun
from app.util.identifiers import assert_safe_ident, quote_ident


async def _dataset_stale(session: AsyncSession, condition: dict) -> tuple[bool, dict]:
    dataset_id = uuid.UUID(str(condition["dataset_id"]))
    max_age_hours = float(condition.get("max_age_hours", 24))
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        return False, {"error": "dataset not found"}
    latest = ds.updated_at or ds.created_at
    age_hours = (datetime.utcnow() - latest).total_seconds() / 3600
    return age_hours > max_age_hours, {"dataset_id": str(dataset_id), "age_hours": age_hours, "max_age_hours": max_age_hours}


async def _build_failed_twice(session: AsyncSession, condition: dict) -> tuple[bool, dict]:
    pipeline_id = uuid.UUID(str(condition["pipeline_id"]))
    threshold = int(condition.get("threshold", 2))
    rows = (
        await session.execute(
            select(BuildRun)
            .where(BuildRun.pipeline_id == pipeline_id)
            .order_by(BuildRun.created_at.desc())
            .limit(threshold)
        )
    ).scalars().all()
    matched = len(rows) >= threshold and all(r.status == "failed" for r in rows)
    return matched, {"pipeline_id": str(pipeline_id), "checked": len(rows), "threshold": threshold}


async def _object_threshold(session: AsyncSession, user: User, condition: dict) -> tuple[bool, dict]:
    dataset_id = uuid.UUID(str(condition["dataset_id"]))
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        return False, {"error": "dataset not found"}
    column = str(condition["column"])
    op = str(condition.get("op", ">"))
    value = condition.get("value")
    if op not in {">", ">=", "<", "<=", "=", "!="}:
        raise ValueError("unsupported threshold operator")
    assert_safe_ident(column)
    sql = f"SELECT COUNT(*) AS matches FROM {quote_ident(ds.schema_name)}.{quote_ident(ds.table_name)} WHERE {quote_ident(column)} {op} :value"
    result = await governed_query(session, user, sql, params={"value": value}, dataset_ids=[dataset_id], capability="view_data", audit_resource_type="automation_monitor")
    count = int(result["rows"][0].get("matches") or 0) if result["rows"] else 0
    return count > 0, {"dataset_id": str(dataset_id), "column": column, "matches": count}


async def evaluate_monitor(session: AsyncSession, user: User, monitor: AutomationMonitor) -> AutomationMonitorRun:
    condition = monitor.condition or {}
    ctype = condition.get("type")
    if ctype == "dataset_stale":
        matched, details = await _dataset_stale(session, condition)
    elif ctype == "build_failed_twice":
        matched, details = await _build_failed_twice(session, condition)
    elif ctype == "object_threshold":
        matched, details = await _object_threshold(session, user, condition)
    else:
        raise ValueError(f"unknown monitor condition type: {ctype}")

    effects = []
    if matched:
        for effect in monitor.effects or []:
            etype = effect.get("type")
            if etype == "notify":
                target_user_id = uuid.UUID(str(effect.get("user_id") or monitor.owner_id or user.id))
                await create_notification(
                    session,
                    user_id=target_user_id,
                    topic="automation",
                    title=effect.get("title") or monitor.name,
                    body=effect.get("body") or "Automation monitor condition matched.",
                    resource_type="automation_monitor",
                    resource_id=str(monitor.id),
                )
                effects.append({"type": "notify", "user_id": str(target_user_id)})
            elif etype == "ontology_action":
                effects.append({"type": "ontology_action", "status": "queued_for_manual_execution", "action_name": effect.get("action_name")})

    monitor.last_evaluated_at = datetime.utcnow()
    monitor.last_status = "matched" if matched else "clear"
    run = AutomationMonitorRun(
        monitor_id=monitor.id,
        status="succeeded",
        matched=matched,
        details={"condition": condition, "matched": matched, "details": details, "effects": effects},
    )
    session.add(run)
    await session.flush()
    return run
