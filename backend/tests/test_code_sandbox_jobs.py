import uuid
from unittest.mock import MagicMock

import pytest

import app.main  # noqa: F401  # initialize app + job registry import order
from app.code_repo.runner import run_code_tests_sync
import app.jobs.tasks.code_transform as code_transform_task
import app.jobs.tasks.code_test as code_test_task


def test_run_code_tests_sync_fails_closed_without_docker(monkeypatch):
    monkeypatch.setattr("app.notebooks.sandbox.docker_available", lambda: False)
    with pytest.raises(ValueError):
        run_code_tests_sync({"test_x.py": "def test_x(): assert True"}, "test_x.py")


def test_run_code_tests_sync_returns_results(monkeypatch):
    monkeypatch.setattr("app.notebooks.sandbox.docker_available", lambda: True)
    monkeypatch.setattr(
        "app.notebooks.sandbox.run_tests",
        lambda files, test_file: {"results": [{"name": "test_x", "status": "passed", "message": None}]},
    )
    out = run_code_tests_sync({"test_x.py": "x"}, "test_x.py")
    assert out[0]["status"] == "passed"


def test_run_code_tests_sync_surfaces_error(monkeypatch):
    monkeypatch.setattr("app.notebooks.sandbox.docker_available", lambda: True)
    monkeypatch.setattr("app.notebooks.sandbox.run_tests", lambda files, test_file: {"error": "boom"})
    out = run_code_tests_sync({"test_x.py": "x"}, "test_x.py")
    assert out[0]["status"] == "error"


def test_code_execution_job_types_registered():
    from app.jobs.registry import REGISTERED_JOB_TYPES

    assert "code_transform" in REGISTERED_JOB_TYPES
    assert "code_test" in REGISTERED_JOB_TYPES
