import uuid

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock

from app.applications.models import Application
from app.applications.router import _require_app_cap
from app.auth.models import User
from app.ml.models import MLModel
from app.ml.router import _require_model_cap


def _session_returning(obj):
    session = AsyncMock()
    session.get.return_value = obj
    return session


# --- ML models -------------------------------------------------------------

@pytest.mark.asyncio
async def test_require_model_cap_owner_allowed(monkeypatch):
    user = User(id=uuid.uuid4(), email="o@example.com")
    model = MLModel(id=uuid.uuid4(), owner_id=user.id)
    monkeypatch.setattr("app.ml.router.effective_capabilities_for_object", AsyncMock(return_value=set()))
    result = await _require_model_cap(_session_returning(model), user, model.id, "view_metadata")
    assert result is model


@pytest.mark.asyncio
async def test_require_model_cap_non_owner_with_grant_allowed(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    model = MLModel(id=uuid.uuid4(), owner_id=uuid.uuid4())
    monkeypatch.setattr("app.ml.router.effective_capabilities_for_object", AsyncMock(return_value={"view_metadata"}))
    result = await _require_model_cap(_session_returning(model), user, model.id, "view_metadata")
    assert result is model


@pytest.mark.asyncio
async def test_require_model_cap_non_owner_without_grant_denied(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    model = MLModel(id=uuid.uuid4(), owner_id=uuid.uuid4())
    monkeypatch.setattr("app.ml.router.effective_capabilities_for_object", AsyncMock(return_value={"view_metadata"}))
    with pytest.raises(HTTPException) as exc:
        await _require_model_cap(_session_returning(model), user, model.id, "manage")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_model_cap_manage_grants_everything(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    model = MLModel(id=uuid.uuid4(), owner_id=uuid.uuid4())
    monkeypatch.setattr("app.ml.router.effective_capabilities_for_object", AsyncMock(return_value={"manage"}))
    result = await _require_model_cap(_session_returning(model), user, model.id, "run")
    assert result is model


@pytest.mark.asyncio
async def test_require_model_cap_missing_is_404():
    user = User(id=uuid.uuid4(), email="v@example.com")
    with pytest.raises(HTTPException) as exc:
        await _require_model_cap(_session_returning(None), user, uuid.uuid4(), "view_metadata")
    assert exc.value.status_code == 404


def test_job_model_has_no_updated_at():
    """Guards the model-detail crash fix: get_model_detail must read fields that
    actually exist on Job (started_at/finished_at), not updated_at."""
    from app.jobs.models import Job

    cols = set(Job.__table__.columns.keys())
    assert "updated_at" not in cols
    assert {"created_at", "started_at", "finished_at"} <= cols


# --- Applications ----------------------------------------------------------

@pytest.mark.asyncio
async def test_require_app_cap_owner_allowed(monkeypatch):
    user = User(id=uuid.uuid4(), email="o@example.com")
    app = Application(id=uuid.uuid4(), name="A", owner_id=user.id)
    monkeypatch.setattr("app.applications.router.effective_capabilities_for_object", AsyncMock(return_value=set()))
    result = await _require_app_cap(_session_returning(app), user, app.id, "edit")
    assert result is app


@pytest.mark.asyncio
async def test_require_app_cap_non_owner_with_grant_allowed(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    app = Application(id=uuid.uuid4(), name="A", owner_id=uuid.uuid4())
    monkeypatch.setattr("app.applications.router.effective_capabilities_for_object", AsyncMock(return_value={"edit"}))
    result = await _require_app_cap(_session_returning(app), user, app.id, "edit")
    assert result is app


@pytest.mark.asyncio
async def test_require_app_cap_non_owner_without_grant_is_404(monkeypatch):
    """Unauthorized access returns 404 to avoid leaking existence."""
    user = User(id=uuid.uuid4(), email="v@example.com")
    app = Application(id=uuid.uuid4(), name="A", owner_id=uuid.uuid4())
    monkeypatch.setattr("app.applications.router.effective_capabilities_for_object", AsyncMock(return_value={"view_metadata"}))
    with pytest.raises(HTTPException) as exc:
        await _require_app_cap(_session_returning(app), user, app.id, "publish")
    assert exc.value.status_code == 404
