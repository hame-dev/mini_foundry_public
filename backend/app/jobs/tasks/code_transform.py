"""Code Repository @transform execution task (runs in the worker, which has
Docker access). User code runs only inside the locked-down sandbox."""
from __future__ import annotations

import uuid
from typing import Any

from app.jobs.registry import job_task


@job_task("code_transform")
def run(session, job, input: dict[str, Any]) -> dict[str, Any]:
    from app.code_repo.runner import run_code_transform_sync

    user_id = uuid.UUID(input["user_id"]) if input.get("user_id") else None
    return run_code_transform_sync(
        session, user_id, input["files"], input.get("requirements") or []
    )
