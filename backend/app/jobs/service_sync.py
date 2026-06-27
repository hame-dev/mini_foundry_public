"""Sync helpers for Celery workers.

Workers run sync SQLAlchemy. Keep these tiny — they're only state
transitions on the `jobs` table.
"""
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.jobs.models import JOB_TRANSITIONS, Job, JobAttempt, JobLogEvent


class InvalidJobTransition(ValueError):
    pass


def _transition(job: Job, new_status: str) -> None:
    allowed = JOB_TRANSITIONS.get(job.status, set())
    if new_status not in allowed:
        raise InvalidJobTransition(f"{job.status} -> {new_status} not allowed")
    job.status = new_status


def _current_attempt(session: Session, job: Job) -> JobAttempt:
    attempt = (
        session.query(JobAttempt)
        .filter(JobAttempt.job_id == job.id, JobAttempt.attempt_number == job.attempt)
        .order_by(JobAttempt.created_at.desc())
        .first()
    )
    if attempt is None:
        attempt = JobAttempt(
            job_id=job.id,
            attempt_number=job.attempt or 1,
            status=job.status,
            celery_task_id=job.celery_task_id,
        )
        session.add(attempt)
        session.flush()
    return attempt


def _log(session: Session, job: Job, attempt: JobAttempt | None, level: str, message: str, payload: dict | None = None) -> None:
    session.add(JobLogEvent(job_id=job.id, attempt_id=attempt.id if attempt else None, level=level, message=message, payload=payload))


def mark_running(session: Session, job: Job) -> None:
    _transition(job, "running")
    now = datetime.utcnow()
    job.started_at = now
    attempt = _current_attempt(session, job)
    attempt.status = "running"
    attempt.started_at = now
    _log(session, job, attempt, "info", "running")


def mark_succeeded(session: Session, job: Job, output: Any) -> None:
    _transition(job, "succeeded")
    job.output = output if isinstance(output, (dict, list)) else {"result": output}
    now = datetime.utcnow()
    job.finished_at = now
    attempt = _current_attempt(session, job)
    attempt.status = "succeeded"
    attempt.finished_at = now
    _log(session, job, attempt, "info", "succeeded")


def mark_failed(session: Session, job: Job, error: str) -> None:
    if job.status not in {"queued", "running"}:
        return  # already in a terminal state, don't overwrite
    job.status = "failed"
    job.error = error[:4000]
    now = datetime.utcnow()
    job.finished_at = now
    attempt = _current_attempt(session, job)
    attempt.status = "failed"
    attempt.finished_at = now
    attempt.error = job.error
    _log(session, job, attempt, "error", "failed", {"error": job.error})


def report_progress(session: Session, job: Job, percent: float, message: str | None = None) -> None:
    job.progress = {"percent": max(0.0, min(100.0, percent)), "message": message}
    attempt = _current_attempt(session, job)
    _log(session, job, attempt, "info", message or "progress", {"percent": job.progress["percent"]})
    session.commit()
