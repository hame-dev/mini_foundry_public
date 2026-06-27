import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from app.auth.models import User
from app.data.models import Dataset
from app.platform.models import DatasetVersion
import app.data.router as dr


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(dr, "log_event", AsyncMock())
    monkeypatch.setattr(dr, "effective_capabilities_for_object", AsyncMock(return_value={"manage", "edit", "view_metadata"}))


def _user():
    return User(id=uuid.uuid4(), email="o@example.com")


def _session():
    s = AsyncMock()
    s.flush = AsyncMock()
    s.commit = AsyncMock()
    return s


# --- rule CRUD validation --------------------------------------------------

@pytest.mark.asyncio
async def test_create_rule_bad_type_400():
    user = _user()
    session = _session()
    session.get.return_value = Dataset(id=uuid.uuid4(), name="d", table_name="t", owner_id=user.id)
    with pytest.raises(HTTPException) as exc:
        await dr.create_quality_rule(uuid.uuid4(), dr.QualityRuleIn(column_name="c", rule_type="bogus"), session, user)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_rule_bad_severity_400():
    user = _user()
    session = _session()
    session.get.return_value = Dataset(id=uuid.uuid4(), name="d", table_name="t", owner_id=user.id)
    with pytest.raises(HTTPException) as exc:
        await dr.create_quality_rule(uuid.uuid4(), dr.QualityRuleIn(column_name="c", rule_type="not_null", severity="loud"), session, user)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_rule_requires_column():
    user = _user()
    session = _session()
    session.get.return_value = Dataset(id=uuid.uuid4(), name="d", table_name="t", owner_id=user.id)
    with pytest.raises(HTTPException) as exc:
        await dr.create_quality_rule(uuid.uuid4(), dr.QualityRuleIn(rule_type="not_null"), session, user)
    assert exc.value.status_code == 400


# --- quality run status mapping --------------------------------------------

@pytest.mark.asyncio
async def test_quality_run_failed_status(monkeypatch):
    user = _user()
    ds_id = uuid.uuid4()
    ds = Dataset(id=ds_id, name="d", table_name="t", owner_id=user.id, current_version_id=uuid.uuid4())
    session = _session()
    version = DatasetVersion(id=ds.current_version_id, dataset_id=ds_id, version_number=1, quality_status="unknown")

    def get(model, _id):
        return ds if model is Dataset else version
    session.get.side_effect = get
    res = MagicMock()
    res.scalars.return_value.all.return_value = []
    session.execute.return_value = res

    monkeypatch.setattr(dr, "validate_expectations_async", AsyncMock(return_value=[
        {"expectation_id": str(uuid.uuid4()), "column_name": "c", "rule_type": "not_null", "severity": "error", "passed": False, "failed_records_count": 3, "error_message": "bad"},
    ]))

    out = await dr.run_quality_checks(ds_id, session, user)
    assert out.status == "failed"
    assert version.quality_status == "failed"


@pytest.mark.asyncio
async def test_quality_run_warning_status(monkeypatch):
    user = _user()
    ds_id = uuid.uuid4()
    ds = Dataset(id=ds_id, name="d", table_name="t", owner_id=user.id, current_version_id=None)
    session = _session()
    session.get.side_effect = lambda model, _id: ds
    res = MagicMock()
    res.scalars.return_value.all.return_value = []
    session.execute.return_value = res
    monkeypatch.setattr(dr, "validate_expectations_async", AsyncMock(return_value=[
        {"expectation_id": str(uuid.uuid4()), "column_name": "c", "rule_type": "max", "severity": "warn", "passed": False, "failed_records_count": 1, "error_message": "warn"},
    ]))
    out = await dr.run_quality_checks(ds_id, session, user)
    assert out.status == "warning"


# --- promote gate ----------------------------------------------------------

@pytest.mark.asyncio
async def test_promote_blocked_on_failed_quality():
    user = _user()
    ds_id = uuid.uuid4()
    vid = uuid.uuid4()
    ds = Dataset(id=ds_id, name="d", table_name="t", owner_id=user.id, current_version_id=None)
    version = DatasetVersion(id=vid, dataset_id=ds_id, version_number=2, quality_status="failed")
    session = _session()
    session.get.side_effect = lambda model, _id: ds if model is Dataset else version
    with pytest.raises(HTTPException) as exc:
        await dr.promote_dataset_version(ds_id, vid, session, user, force=False)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_promote_force_overrides_failed_quality():
    user = _user()
    ds_id = uuid.uuid4()
    vid = uuid.uuid4()
    ds = Dataset(id=ds_id, name="d", table_name="t", owner_id=user.id, current_version_id=None)
    version = DatasetVersion(id=vid, dataset_id=ds_id, version_number=2, quality_status="failed")
    session = _session()
    session.get.side_effect = lambda model, _id: ds if model is Dataset else version
    out = await dr.promote_dataset_version(ds_id, vid, session, user, force=True)
    assert out["ok"] is True
    assert ds.current_version_id == vid


# --- freshness -------------------------------------------------------------

@pytest.mark.asyncio
async def test_freshness_fresh_vs_stale():
    user = _user()
    ds_id = uuid.uuid4()
    ds = Dataset(id=ds_id, name="d", table_name="t", owner_id=user.id, freshness_window_seconds=3600)
    session = _session()
    session.get.return_value = ds
    recent = DatasetVersion(id=uuid.uuid4(), dataset_id=ds_id, version_number=1,
                            created_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    res = MagicMock()
    res.scalar_one_or_none.return_value = recent
    session.execute.return_value = res
    out = await dr.get_freshness(ds_id, session, user)
    assert out.status == "fresh"

    recent.created_at = datetime.now(timezone.utc) - timedelta(hours=5)
    out2 = await dr.get_freshness(ds_id, session, user)
    assert out2.status == "stale"


@pytest.mark.asyncio
async def test_freshness_unknown_without_window():
    user = _user()
    ds_id = uuid.uuid4()
    ds = Dataset(id=ds_id, name="d", table_name="t", owner_id=user.id, freshness_window_seconds=None)
    session = _session()
    session.get.return_value = ds
    recent = DatasetVersion(id=uuid.uuid4(), dataset_id=ds_id, version_number=1, created_at=datetime.now(timezone.utc))
    res = MagicMock()
    res.scalar_one_or_none.return_value = recent
    session.execute.return_value = res
    out = await dr.get_freshness(ds_id, session, user)
    assert out.status == "unknown"
