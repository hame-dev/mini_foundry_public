"""Notebook cell execution task. Implemented as part of v0.5.

This module is imported by `celery_app.py` even before v0.5 lands; the
@job_task registration sits idle until notebook cells are actually
enqueued. The full body is filled in by app.notebooks.execution.
"""
from __future__ import annotations

from typing import Any

from app.jobs.registry import job_task


@job_task("notebook_cell")
def run(session, job, input: dict[str, Any]) -> dict[str, Any]:
    # Delegated to app.notebooks.execution.execute_cell_in_worker so that
    # the cell-specific logic lives next to the rest of the notebook code.
    from app.notebooks.execution import execute_cell_in_worker
    return execute_cell_in_worker(session, job, input)
