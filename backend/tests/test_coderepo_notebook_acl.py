import uuid

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock

from app.auth.models import User
from app.code_repo.models import CodeRepository
from app.code_repo.router import _require_repo_cap, DEMO_REPO_ID
from app.notebooks.models import Notebook
from app.notebooks.router import _can_view, _can_edit, _can_run, _can_manage


def _session_returning(obj):
    session = AsyncMock()
    session.get.return_value = obj
    return session


# --- code repositories -----------------------------------------------------

@pytest.mark.asyncio
async def test_repo_owner_allowed(monkeypatch):
    user = User(id=uuid.uuid4(), email="o@example.com")
    repo = CodeRepository(id=uuid.uuid4(), name="r", owner_id=user.id)
    monkeypatch.setattr("app.code_repo.router.effective_capabilities_for_object", AsyncMock(return_value=set()))
    assert await _require_repo_cap(_session_returning(repo), user, repo.id, "edit") is repo


@pytest.mark.asyncio
async def test_repo_demo_open_to_all(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    repo = CodeRepository(id=DEMO_REPO_ID, name="demo", owner_id=uuid.uuid4())
    monkeypatch.setattr("app.code_repo.router.effective_capabilities_for_object", AsyncMock(return_value=set()))
    assert await _require_repo_cap(_session_returning(repo), user, repo.id, "edit") is repo


@pytest.mark.asyncio
async def test_repo_non_owner_with_grant_allowed(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    repo = CodeRepository(id=uuid.uuid4(), name="r", owner_id=uuid.uuid4())
    monkeypatch.setattr("app.code_repo.router.effective_capabilities_for_object", AsyncMock(return_value={"edit"}))
    assert await _require_repo_cap(_session_returning(repo), user, repo.id, "edit") is repo


@pytest.mark.asyncio
async def test_repo_non_owner_without_grant_denied(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    repo = CodeRepository(id=uuid.uuid4(), name="r", owner_id=uuid.uuid4())
    monkeypatch.setattr("app.code_repo.router.effective_capabilities_for_object", AsyncMock(return_value={"view_metadata"}))
    with pytest.raises(HTTPException) as exc:
        await _require_repo_cap(_session_returning(repo), user, repo.id, "edit")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_repo_manage_grants_everything(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    repo = CodeRepository(id=uuid.uuid4(), name="r", owner_id=uuid.uuid4())
    monkeypatch.setattr("app.code_repo.router.effective_capabilities_for_object", AsyncMock(return_value={"manage"}))
    assert await _require_repo_cap(_session_returning(repo), user, repo.id, "edit") is repo


# --- notebooks -------------------------------------------------------------

def _nb(owner_id):
    return Notebook(id=uuid.uuid4(), title="n", owner_id=owner_id)


@pytest.mark.asyncio
async def test_notebook_owner_allowed_all():
    user = User(id=uuid.uuid4(), email="o@example.com")
    nb = _nb(user.id)
    session = AsyncMock()
    assert await _can_view(session, user, nb)
    assert await _can_edit(session, user, nb)
    assert await _can_run(session, user, nb)
    assert await _can_manage(session, user, nb)


@pytest.mark.asyncio
async def test_notebook_acl_grant_authorizes(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    nb = _nb(uuid.uuid4())
    monkeypatch.setattr("app.notebooks.router.effective_capabilities_for_object", AsyncMock(return_value={"view_metadata"}))
    assert await _can_view(AsyncMock(), user, nb)


@pytest.mark.asyncio
async def test_notebook_run_requires_run_cap(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    nb = _nb(uuid.uuid4())
    monkeypatch.setattr("app.notebooks.router.effective_capabilities_for_object", AsyncMock(return_value={"run"}))
    # legacy fallback returns no permission
    monkeypatch.setattr(
        "app.notebooks.router.effective_notebook_permission",
        AsyncMock(return_value=type("E", (), {"can_view": False, "can_edit": False, "can_run": False, "can_manage": False})()),
    )
    assert await _can_run(AsyncMock(), user, nb)


@pytest.mark.asyncio
async def test_notebook_no_grant_falls_back_to_legacy_denied(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    nb = _nb(uuid.uuid4())
    monkeypatch.setattr("app.notebooks.router.effective_capabilities_for_object", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        "app.notebooks.router.effective_notebook_permission",
        AsyncMock(return_value=type("E", (), {"can_view": False, "can_edit": False, "can_run": False, "can_manage": False})()),
    )
    assert not await _can_view(AsyncMock(), user, nb)
    assert not await _can_manage(AsyncMock(), user, nb)
