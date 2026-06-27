"""Async service used by web routes to enqueue jobs and read job state."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.logger import log_event
from app.auth.models import User
from app.jobs.celery_app import celery_app
from app.jobs.models import JOB_TRANSITIONS, Job, JobAttempt, JobLogEvent


class InvalidJobTransition(ValueError):
    pass


_PENDING_DISPATCH_KEY = "mini_foundry_pending_job_dispatches"


def _send_job_to_celery(job_type: str, job_id: str, task_id: str | None = None) -> str:
    task_id = task_id or job_id
    celery_app.send_task(job_type, args=[job_id], task_id=task_id)
    return task_id


def _dispatch_pending_jobs(sync_session) -> None:  # noqa: ANN001 - SQLAlchemy event hook
    pending: list[tuple[str, str, str]] = sync_session.info.pop(_PENDING_DISPATCH_KEY, [])
    for job_type, job_id, task_id in pending:
        _send_job_to_celery(job_type, job_id, task_id)


def _discard_pending_jobs(sync_session) -> None:  # noqa: ANN001 - SQLAlchemy event hook
    sync_session.info.pop(_PENDING_DISPATCH_KEY, None)


def _dispatch_after_commit(session: AsyncSession, job: Job, task_id: str | None = None) -> None:
    """Publish Celery tasks only after the DB transaction commits.

    Publishing before commit lets a fast worker run before it can see the
    freshly inserted job row, leaving the DB job stuck in `queued`.
    """

    sync_session = session.sync_session
    pending = sync_session.info.setdefault(_PENDING_DISPATCH_KEY, [])
    if not pending:
        event.listen(sync_session, "after_commit", _dispatch_pending_jobs, once=True)
        event.listen(sync_session, "after_rollback", _discard_pending_jobs, once=True)
    task_id = task_id or str(job.id)
    pending.append((job.job_type, str(job.id), task_id))
    job.celery_task_id = task_id


async def enqueue(
    session: AsyncSession,
    *,
    user: User | None,
    job_type: str,
    input: dict[str, Any],
    resource_type: str | None = None,
    resource_id: str | None = None,
    idempotency_key: str | None = None,
) -> Job:
    if idempotency_key:
        existing = (
            await session.execute(
                select(Job).where(Job.idempotency_key == idempotency_key, Job.status.in_(["queued", "running", "succeeded"]))
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    job = Job(
        user_id=user.id if user else None,
        job_type=job_type,
        status="queued",
        input=input,
        resource_type=resource_type,
        resource_id=resource_id,
        idempotency_key=idempotency_key,
    )
    session.add(job)
    await session.flush()
    attempt = JobAttempt(job_id=job.id, attempt_number=job.attempt, status="queued", celery_task_id=str(job.id))
    session.add(attempt)
    await session.flush()
    session.add(JobLogEvent(job_id=job.id, attempt_id=attempt.id, level="info", message="queued", payload={"job_type": job_type}))

    _dispatch_after_commit(session, job)

    await log_event(
        session, user=user, event_type="JOB_STARTED",
        resource_type="job", resource_id=str(job.id),
        input_summary={"job_type": job_type, "resource_type": resource_type, "resource_id": resource_id},
    )
    return job


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> Job | None:
    return await session.get(Job, job_id)


async def list_jobs(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[Job]:
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if user_id is not None:
        stmt = stmt.where(Job.user_id == user_id)
    if status is not None:
        stmt = stmt.where(Job.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def cancel_job(session: AsyncSession, job: Job) -> None:
    if job.status not in {"queued", "running"}:
        raise InvalidJobTransition(f"cannot cancel from {job.status}")
    celery_app.control.revoke(job.celery_task_id or str(job.id), terminate=True)
    job.status = "cancelled"


async def retry_job(session: AsyncSession, job: Job) -> None:
    if job.status not in {"queued", "failed", "timed_out"}:
        raise InvalidJobTransition(f"cannot retry from {job.status}")
    job.status = "queued"
    job.error = None
    job.output = None
    job.progress = None
    job.started_at = None
    job.finished_at = None
    job.attempt = int(job.attempt or 1) + 1
    task_id = str(uuid.uuid4())
    attempt = JobAttempt(job_id=job.id, attempt_number=job.attempt, status="queued", celery_task_id=task_id)
    session.add(attempt)
    await session.flush()
    session.add(JobLogEvent(job_id=job.id, attempt_id=attempt.id, level="info", message="retry queued", payload={"task_id": task_id}))
    _dispatch_after_commit(session, job, task_id)


async def list_job_attempts(session: AsyncSession, job_id: uuid.UUID) -> list[JobAttempt]:
    rows = await session.execute(select(JobAttempt).where(JobAttempt.job_id == job_id).order_by(JobAttempt.attempt_number.desc()))
    return list(rows.scalars().all())


async def list_job_log_events(session: AsyncSession, job_id: uuid.UUID, limit: int = 200) -> list[JobLogEvent]:
    rows = await session.execute(select(JobLogEvent).where(JobLogEvent.job_id == job_id).order_by(JobLogEvent.created_at.desc()).limit(limit))
    return list(rows.scalars().all())
