"""Code Repository test execution task (runs in the worker). User test code
runs only inside the locked-down sandbox."""
from __future__ import annotations

from typing import Any

from app.jobs.registry import job_task


@job_task("code_test")
def run(session, job, input: dict[str, Any]) -> dict[str, Any]:
    from app.code_repo.runner import run_code_tests_sync

    results = run_code_tests_sync(input["files"], input["test_file"])
    return {"results": results}
