"""Dispatch + helper tests for sandboxed Code Repository transforms.

After the sandbox-safety milestone, user code never runs in a backend process:
the default path is sandbox-only and fails closed when Docker is unavailable.
"""
import uuid
from unittest.mock import MagicMock

import pytest

from app.code_repo.runner import run_code_transform, run_code_transform_sync
from app.config import get_settings
from app.notebooks.sandbox import run_transform, safe_output_stem


def test_safe_output_stem_matches_sdk_naming():
    assert safe_output_stem("My Output!") == "my_output"
    assert safe_output_stem("orders_2024") == "orders_2024"


def test_run_transform_rejects_invalid_mode():
    with pytest.raises(ValueError):
        run_transform({"transforms.py": "x"}, "transforms.py", mode="bogus")


@pytest.mark.asyncio
async def test_dispatch_fails_closed_without_docker(monkeypatch):
    monkeypatch.setattr("app.notebooks.sandbox.docker_available", lambda: False)
    monkeypatch.setattr(get_settings(), "allow_inprocess_code_exec", False)
    with pytest.raises(ValueError):
        await run_code_transform(MagicMock(), uuid.uuid4(), {"transforms.py": "x"})


@pytest.mark.asyncio
async def test_dispatch_uses_sandbox_when_docker_available(monkeypatch):
    monkeypatch.setattr("app.notebooks.sandbox.docker_available", lambda: True)

    async def fake_sandbox(session, user_id, files):
        return {"status": "success", "transforms": [{"output_dataset_name": "o"}], "isolation": "docker"}

    monkeypatch.setattr("app.code_repo.runner._run_code_transform_sandbox", fake_sandbox)
    res = await run_code_transform(MagicMock(), uuid.uuid4(), {"transforms.py": "x"})
    assert res["isolation"] == "docker"


def test_sync_runner_fails_closed_without_docker(monkeypatch):
    monkeypatch.setattr("app.notebooks.sandbox.docker_available", lambda: False)
    with pytest.raises(ValueError):
        run_code_transform_sync(MagicMock(), uuid.uuid4(), {"transforms.py": "x"})


def test_sync_runner_rejects_requirements(monkeypatch):
    monkeypatch.setattr("app.notebooks.sandbox.docker_available", lambda: True)
    with pytest.raises(ValueError, match="requirements"):
        run_code_transform_sync(MagicMock(), uuid.uuid4(), {"transforms.py": "x"}, requirements=["scipy"])
