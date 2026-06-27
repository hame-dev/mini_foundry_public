from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.automation.models import AutomationMonitor, AutomationMonitorRun
from app.automation.service import evaluate_monitor
from app.deps import CurrentUserDep, SessionDep
from app.platform.service import upsert_resource

router = APIRouter(prefix="/automation/monitors", tags=["automation"])


class MonitorIn(BaseModel):
    name: str
    description: str | None = None
    condition: dict
    effects: list[dict] = []
    enabled: bool = True


class MonitorOut(BaseModel):
    id: str
    name: str
    description: str | None
    condition: dict
    effects: list
    enabled: bool
    last_evaluated_at: datetime | None
    last_status: str
    created_at: datetime


def _out(row: AutomationMonitor) -> MonitorOut:
    return MonitorOut(
        id=str(row.id),
        name=row.name,
        description=row.description,
        condition=row.condition,
        effects=row.effects or [],
        enabled=row.enabled,
        last_evaluated_at=row.last_evaluated_at,
        last_status=row.last_status,
        created_at=row.created_at,
    )


@router.get("", response_model=list[MonitorOut])
async def list_monitors(session: SessionDep, user: CurrentUserDep) -> list[MonitorOut]:
    rows = (
        await session.execute(
            select(AutomationMonitor)
            .where(AutomationMonitor.owner_id == user.id)
            .order_by(AutomationMonitor.created_at.desc())
        )
    ).scalars().all()
    return [_out(row) for row in rows]


@router.post("", response_model=MonitorOut, status_code=201)
async def create_monitor(payload: MonitorIn, session: SessionDep, user: CurrentUserDep) -> MonitorOut:
    row = AutomationMonitor(
        name=payload.name,
        description=payload.description,
        condition=payload.condition,
        effects=payload.effects,
        enabled=payload.enabled,
        owner_id=user.id,
    )
    session.add(row)
    await session.flush()
    await upsert_resource(
        session,
        resource_type="workflow",
        object_id=row.id,
        name=row.name,
        owner_user_id=user.id,
        metadata={"kind": "automation_monitor", "condition": row.condition},
    )
    await session.commit()
    return _out(row)


@router.post("/{monitor_id}/evaluate")
async def evaluate(monitor_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    row = await session.get(AutomationMonitor, monitor_id)
    if row is None or row.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "monitor not found")
    if not row.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "monitor disabled")
    run = await evaluate_monitor(session, user, row)
    await session.commit()
    return {"run_id": str(run.id), "matched": run.matched, "details": run.details}


@router.get("/{monitor_id}/runs")
async def monitor_runs(monitor_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    row = await session.get(AutomationMonitor, monitor_id)
    if row is None or row.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "monitor not found")
    runs = (
        await session.execute(
            select(AutomationMonitorRun)
            .where(AutomationMonitorRun.monitor_id == monitor_id)
            .order_by(AutomationMonitorRun.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return {
        "runs": [
            {
                "id": str(run.id),
                "status": run.status,
                "matched": run.matched,
                "details": run.details,
                "created_at": run.created_at.isoformat(),
            }
            for run in runs
        ]
    }
