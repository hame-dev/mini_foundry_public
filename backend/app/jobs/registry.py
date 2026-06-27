"""Decorator-registered job types.

Use `@job_task("csv_profile")` to register a sync function that receives a
`job_id` and runs inside a Celery worker. The wrapper:
  * opens a *sync* SQLAlchemy session (`SYNC_DATABASE_URL`)
  * marks the job running, calls the user fn, marks succeeded/failed
  * stores any returned dict in `jobs.output`
  * captures uncaught exceptions into `jobs.error`
"""
from __future__ import annotations

import traceback
from datetime import datetime
from functools import wraps
from typing import Any, Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.jobs.celery_app import celery_app


REGISTERED_JOB_TYPES: set[str] = set()


def _sync_session_factory() -> sessionmaker[Session]:
    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)


_SessionLocalSync = None


def _get_session_factory() -> sessionmaker[Session]:
    global _SessionLocalSync
    if _SessionLocalSync is None:
        _SessionLocalSync = _sync_session_factory()
    return _SessionLocalSync


def job_task(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a sync function as a Celery task named `name`.

    The wrapped function receives `(session, job, input_dict)` and returns
    a dict (or None) that becomes `jobs.output`.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        REGISTERED_JOB_TYPES.add(name)

        @celery_app.task(name=name, bind=True)
        @wraps(fn)
        def wrapper(self, job_id: str) -> Any:  # noqa: ANN001
            from app.jobs.models import Job  # local import to avoid cycle
            from app.jobs.service_sync import mark_failed, mark_running, mark_succeeded

            Session = _get_session_factory()
            with Session() as session:
                job: Job | None = session.get(Job, job_id)
                if job is None:
                    return {"error": "job row missing"}
                try:
                    mark_running(session, job)
                    session.commit()
                    output = fn(session, job, job.input or {})
                    mark_succeeded(session, job, output)
                    session.commit()
                    return output
                except Exception as exc:  # noqa: BLE001
                    session.rollback()
                    # reopen because rollback drops the loaded job
                    job = session.get(Job, job_id)
                    if job is not None:
                        mark_failed(session, job, f"{exc}\n\n{traceback.format_exc()}")
                        session.commit()
                    raise

        return wrapper

    return decorator
