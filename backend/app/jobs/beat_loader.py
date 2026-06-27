"""Load schedules from the DB into Celery Beat at startup.

Beat reads `celery_app.conf.beat_schedule`, which is a dict. We populate it
from the `schedules` table. Edits to schedules require a Beat restart;
the `/admin/schedules` router sets a `beat:reload` Redis flag (consumed
externally — e.g. by a watchdog that `docker compose restart beat`s).
"""
from __future__ import annotations

import uuid

from celery.schedules import crontab
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from app.config import get_settings
from app.jobs.celery_app import celery_app
from app.jobs.models import Schedule


def _parse_cron(expr: str) -> crontab | None:
    parts = expr.strip().split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    try:
        return crontab(minute=minute, hour=hour, day_of_month=dom, month_of_year=month, day_of_week=dow)
    except Exception:
        return None


def load_schedules_into_beat() -> None:
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    schedule_entries: dict[str, dict] = {}

    with Session() as session:
        rows = session.execute(select(Schedule).where(Schedule.enabled == True)).scalars().all()  # noqa: E712
        for s in rows:
            ct = _parse_cron(s.cron_expression)
            if ct is None:
                continue
            schedule_entries[f"schedule-{s.id}"] = {
                "task": s.job_type,
                "schedule": ct,
                # Each fire enqueues a fresh job_id; the task wrapper expects
                # the job row to already exist, so the schedule wrapper task
                # below creates it on the fly.
                "args": [str(s.id)],
            }

    celery_app.conf.beat_schedule = schedule_entries


@celery_app.task(name="_schedule_fire")
def fire_schedule(schedule_id: str) -> None:
    """Beat-triggered wrapper: create a Job for the given Schedule and
    dispatch the underlying job_type with that fresh job_id."""
    from app.jobs.models import Job
    from datetime import datetime

    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as session:
        sched = session.get(Schedule, uuid.UUID(schedule_id))
        if sched is None or not sched.enabled:
            return
        job = Job(
            user_id=sched.owner_id,
            job_type=sched.job_type,
            status="queued",
            input=sched.input or {},
            resource_type="schedule",
            resource_id=str(sched.id),
        )
        session.add(job)
        session.flush()
        job.celery_task_id = str(job.id)
        sched.last_run_at = datetime.utcnow()
        session.commit()
        celery_app.send_task(sched.job_type, args=[str(job.id)], task_id=str(job.id))


# Re-point each schedule's task to the _schedule_fire wrapper so we can
# materialize a Job row before the real task runs.
def install_schedule_indirection() -> None:
    for name, entry in celery_app.conf.beat_schedule.items():
        sched_id = entry["args"][0] if entry.get("args") else None
        if sched_id is None:
            continue
        entry["task"] = "_schedule_fire"


if __name__ == "__main__":
    # Beat container can run `python -m app.jobs.beat_loader` once before
    # `celery -A app.jobs.celery_app beat` to populate the schedule.
    load_schedules_into_beat()
    install_schedule_indirection()
    print(f"Loaded {len(celery_app.conf.beat_schedule)} schedule entries")
