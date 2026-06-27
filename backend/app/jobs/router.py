import uuid
import asyncio
import json
from datetime import datetime
from typing import Any

from croniter import croniter
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.audit.logger import log_event
from app.cache.redis_client import get_redis
from app.db import SessionLocal
from app.deps import AdminDep, CurrentUserDep, SessionDep, StreamUserDep
from app.jobs import service
from app.jobs import tasks  # noqa: F401  # ensure REGISTERED_JOB_TYPES is populated
from app.jobs.models import Job, JobAttempt, JobLogEvent, Schedule
from app.jobs.registry import REGISTERED_JOB_TYPES


router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobOut(BaseModel):
    id: str
    user_id: str | None
    job_type: str
    status: str
    input: dict | None
    output: dict | None
    error: str | None
    progress: dict | None
    resource_type: str | None
    resource_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobAttemptOut(BaseModel):
    id: str
    attempt_number: int
    celery_task_id: str | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    created_at: datetime


class JobLogEventOut(BaseModel):
    id: str
    attempt_id: str | None
    level: str
    message: str
    payload: dict | None
    created_at: datetime


class JobDetailOut(JobOut):
    attempts: list[JobAttemptOut]
    log_events: list[JobLogEventOut]


def _job_out(j: Job) -> JobOut:
    return JobOut(
        id=str(j.id),
        user_id=str(j.user_id) if j.user_id else None,
        job_type=j.job_type,
        status=j.status,
        input=j.input,
        output=j.output,
        error=j.error,
        progress=j.progress,
        resource_type=j.resource_type,
        resource_id=j.resource_id,
        created_at=j.created_at,
        started_at=j.started_at,
        finished_at=j.finished_at,
    )


def _attempt_out(a: JobAttempt) -> JobAttemptOut:
    return JobAttemptOut(
        id=str(a.id), attempt_number=a.attempt_number, celery_task_id=a.celery_task_id,
        status=a.status, started_at=a.started_at, finished_at=a.finished_at,
        error=a.error, created_at=a.created_at,
    )


def _log_event_out(e: JobLogEvent) -> JobLogEventOut:
    return JobLogEventOut(
        id=str(e.id), attempt_id=str(e.attempt_id) if e.attempt_id else None,
        level=e.level, message=e.message, payload=e.payload, created_at=e.created_at,
    )


@router.get("", response_model=list[JobOut])
async def list_jobs(
    session: SessionDep, user: CurrentUserDep,
    status: str | None = None, mine: bool = True, limit: int = 100,
) -> list[JobOut]:
    if mine:
        user_id = user.id
    else:
        from app.auth.service import get_user_roles
        roles = await get_user_roles(session, user.id)
        if "admin" not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "admin required for global job list")
        user_id = None
    rows = await service.list_jobs(session, user_id=user_id, status=status, limit=limit)
    return [_job_out(j) for j in rows]


@router.get("/_meta/job-types")
async def list_job_types(_: CurrentUserDep) -> dict:
    return {"job_types": sorted(REGISTERED_JOB_TYPES)}


@router.get("/{job_id}", response_model=JobDetailOut)
async def get_job(job_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> JobDetailOut:
    j = await service.get_job(session, job_id)
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if j.user_id != user.id:
        # Non-owners can read only via admin; for MVP allow if admin (deps.require_admin).
        # If you're here without admin, refuse.
        # We can't call AdminDep here without an extra param; quick role check:
        from app.auth.service import get_user_roles
        roles = await get_user_roles(session, user.id)
        if "admin" not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not your job")
    attempts = await service.list_job_attempts(session, job_id)
    logs = await service.list_job_log_events(session, job_id)
    return JobDetailOut(**_job_out(j).model_dump(), attempts=[_attempt_out(a) for a in attempts], log_events=[_log_event_out(e) for e in logs])


async def _require_job_visible(session: SessionDep, job_id: uuid.UUID, user: CurrentUserDep) -> Job:
    j = await service.get_job(session, job_id)
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if j.user_id != user.id:
        from app.auth.service import get_user_roles
        roles = await get_user_roles(session, user.id)
        if "admin" not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not your job")
    return j


@router.get("/{job_id}/stream")
async def stream_job(job_id: uuid.UUID, user: StreamUserDep, interval_seconds: float = 2.0) -> StreamingResponse:
    async with SessionLocal() as session:
        await _require_job_visible(session, job_id, user)
    interval = max(1.0, min(interval_seconds, 30.0))

    async def events():
        sent_log_ids: set[str] = set()
        last_status: str | None = None
        while True:
            chunks: list[str] = []
            done = False
            async with SessionLocal() as stream_session:
                job = await service.get_job(stream_session, job_id)
                if job is None:
                    chunks.append(f"event: error\ndata: {json.dumps({'message': 'job not found'})}\n\n")
                    done = True
                else:
                    payload = _job_out(job).model_dump(mode="json")
                    if job.status != last_status:
                        last_status = job.status
                        chunks.append(f"event: status\ndata: {json.dumps(payload)}\n\n")
                    logs = await service.list_job_log_events(stream_session, job_id)
                    for log in logs:
                        key = str(log.id)
                        if key in sent_log_ids:
                            continue
                        sent_log_ids.add(key)
                        chunks.append(f"event: log\ndata: {json.dumps(_log_event_out(log).model_dump(mode='json'))}\n\n")
                    if job.status in {"succeeded", "failed", "cancelled", "timed_out"}:
                        chunks.append(f"event: done\ndata: {json.dumps(payload)}\n\n")
                        done = True
            for chunk in chunks:
                yield chunk
            if done:
                return
            await asyncio.sleep(interval)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel(job_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> JobOut:
    j = await service.get_job(session, job_id)
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if j.user_id != user.id:
        from app.auth.service import get_user_roles
        roles = await get_user_roles(session, user.id)
        if "admin" not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not your job")
    try:
        await service.cancel_job(session, j)
    except service.InvalidJobTransition as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    await session.commit()
    return _job_out(j)


@router.post("/{job_id}/retry", response_model=JobOut)
async def retry(job_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> JobOut:
    j = await service.get_job(session, job_id)
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if j.user_id != user.id:
        from app.auth.service import get_user_roles
        roles = await get_user_roles(session, user.id)
        if "admin" not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not your job")
    try:
        await service.retry_job(session, j)
    except service.InvalidJobTransition as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    await session.commit()
    return _job_out(j)


# --------------------------------------------------------------- schedules

schedules_router = APIRouter(prefix="/admin/schedules", tags=["schedules"])


class ScheduleIn(BaseModel):
    name: str
    job_type: str
    cron_expression: str
    input: dict[str, Any] | None = None
    enabled: bool = True


class ScheduleOut(BaseModel):
    id: str
    name: str
    job_type: str
    cron_expression: str
    input: dict | None
    enabled: bool
    owner_id: str | None
    created_at: datetime
    last_run_at: datetime | None
    next_run_at: datetime | None


def _schedule_out(s: Schedule) -> ScheduleOut:
    return ScheduleOut(
        id=str(s.id), name=s.name, job_type=s.job_type,
        cron_expression=s.cron_expression, input=s.input, enabled=s.enabled,
        owner_id=str(s.owner_id) if s.owner_id else None,
        created_at=s.created_at, last_run_at=s.last_run_at, next_run_at=s.next_run_at,
    )


def _validate_cron(expr: str) -> None:
    if not croniter.is_valid(expr):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid cron expression: {expr}")


def _validate_job_type(job_type: str) -> None:
    if job_type not in REGISTERED_JOB_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown job_type: {job_type}; known = {sorted(REGISTERED_JOB_TYPES)}",
        )


async def _set_beat_reload_flag() -> None:
    await get_redis().set("beat:reload", "1", ex=3600)


@schedules_router.get("", response_model=list[ScheduleOut])
async def list_schedules(session: SessionDep, _: AdminDep) -> list[ScheduleOut]:
    rows = (await session.execute(select(Schedule).order_by(Schedule.created_at.desc()))).scalars().all()
    return [_schedule_out(s) for s in rows]


@schedules_router.post("", response_model=ScheduleOut)
async def create_schedule(payload: ScheduleIn, session: SessionDep, admin: AdminDep) -> ScheduleOut:
    _validate_cron(payload.cron_expression)
    _validate_job_type(payload.job_type)

    s = Schedule(
        name=payload.name,
        job_type=payload.job_type,
        cron_expression=payload.cron_expression,
        input=payload.input,
        enabled=payload.enabled,
        owner_id=admin.id,
        next_run_at=croniter(payload.cron_expression, datetime.utcnow()).get_next(datetime),
    )
    session.add(s)
    await session.flush()
    await log_event(
        session, user=admin, event_type="SCHEDULE_CREATED",
        resource_type="schedule", resource_id=str(s.id),
        input_summary=payload.model_dump(),
    )
    await session.commit()
    await _set_beat_reload_flag()
    return _schedule_out(s)


@schedules_router.put("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: uuid.UUID, payload: ScheduleIn, session: SessionDep, admin: AdminDep,
) -> ScheduleOut:
    s = await session.get(Schedule, schedule_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "schedule not found")
    _validate_cron(payload.cron_expression)
    _validate_job_type(payload.job_type)
    s.name = payload.name
    s.job_type = payload.job_type
    s.cron_expression = payload.cron_expression
    s.input = payload.input
    s.enabled = payload.enabled
    s.next_run_at = croniter(payload.cron_expression, datetime.utcnow()).get_next(datetime)
    await log_event(
        session, user=admin, event_type="SCHEDULE_CREATED",
        resource_type="schedule", resource_id=str(s.id),
        input_summary={"action": "update", **payload.model_dump()},
    )
    await session.commit()
    await _set_beat_reload_flag()
    return _schedule_out(s)


@schedules_router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    s = await session.get(Schedule, schedule_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "schedule not found")
    await session.delete(s)
    await log_event(
        session, user=admin, event_type="SCHEDULE_CREATED",
        resource_type="schedule", resource_id=str(schedule_id),
        input_summary={"action": "delete"},
    )
    await session.commit()
    await _set_beat_reload_flag()
    return {"ok": True}


@schedules_router.post("/{schedule_id}/run-now")
async def run_schedule_now(schedule_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    s = await session.get(Schedule, schedule_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "schedule not found")
    job = await service.enqueue(
        session, user=admin, job_type=s.job_type, input=s.input or {},
        resource_type="schedule", resource_id=str(s.id),
    )
    s.last_run_at = datetime.utcnow()
    await session.commit()
    return {"job_id": str(job.id)}
