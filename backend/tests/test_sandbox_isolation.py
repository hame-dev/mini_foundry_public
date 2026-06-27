"""Sandbox Docker-host / runtime isolation wiring (Phase 0)."""
from pathlib import Path

from app.notebooks import sandbox


def test_build_command_includes_runtime_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("SANDBOX_RUNTIME", "runsc")
    cmd = sandbox._build_command(tmp_path, None, "c1")
    assert "--runtime=runsc" in cmd
    # still a `docker run` for the configured image
    assert cmd[:2] == ["docker", "run"]


def test_build_command_no_runtime_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SANDBOX_RUNTIME", raising=False)
    monkeypatch.setattr(sandbox, "sandbox_runtime", lambda: "")
    cmd = sandbox._build_command(tmp_path, None, "c1")
    assert not any(part.startswith("--runtime") for part in cmd)


def test_docker_env_sets_host_when_configured(monkeypatch):
    monkeypatch.setenv("SANDBOX_DOCKER_HOST", "tcp://docker-rootless:2375")
    env = sandbox._docker_env()
    assert env is not None
    assert env["DOCKER_HOST"] == "tcp://docker-rootless:2375"


def test_docker_env_none_when_unset(monkeypatch):
    monkeypatch.delenv("SANDBOX_DOCKER_HOST", raising=False)
    monkeypatch.setattr(sandbox, "sandbox_docker_host", lambda: "")
    assert sandbox._docker_env() is None
