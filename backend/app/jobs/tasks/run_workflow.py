"""Async workflow execution task."""
from __future__ import annotations

import uuid
from typing import Any

from app.actions.registry import get_workflow, load_user_workflows
from app.jobs.registry import job_task


# Ensure user workflows are imported in the worker process too.
load_user_workflows()


@job_task("run_workflow")
def run(session, job, input: dict[str, Any]) -> dict[str, Any]:
    from app.auth.models import User
    workflow_key = input["workflow_key"]
    params = input.get("params") or {}
    user_id = input.get("user_id")
    user = session.get(User, uuid.UUID(user_id)) if user_id else None

    wf = get_workflow(workflow_key)
    result = wf["fn"](session, user, params)
    return result if isinstance(result, dict) else {"result": result}
