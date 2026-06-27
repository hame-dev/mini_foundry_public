import uuid

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from app.auth.models import Role, User
from app.data.models import Dataset
import app.governance.admin_router as gov


@pytest.fixture(autouse=True)
def _patch_side_effects(monkeypatch):
    monkeypatch.setattr(gov, "bump_permission_version", AsyncMock(return_value=2))
    monkeypatch.setattr(gov, "log_event", AsyncMock())


def _admin():
    return User(id=uuid.uuid4(), email="a@example.com")


def _session():
    s = AsyncMock()
    s.flush = AsyncMock()
    s.commit = AsyncMock()
    return s


# --- capabilities ----------------------------------------------------------

@pytest.mark.asyncio
async def test_list_capabilities_returns_canonical_set():
    caps = await gov.list_capabilities(_=_admin())
    names = {c.name for c in caps}
    assert "view_metadata" in names and "manage" in names
    assert len(caps) == len(gov.CANONICAL_CAPABILITIES)


# --- roles -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_admin_role_blocked():
    session = _session()
    session.get.return_value = Role(id=uuid.uuid4(), name="admin")
    with pytest.raises(HTTPException) as exc:
        await gov.delete_role(uuid.uuid4(), session, _admin())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_missing_role_404():
    session = _session()
    session.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        await gov.delete_role(uuid.uuid4(), session, _admin())
    assert exc.value.status_code == 404


# --- row policies ----------------------------------------------------------

@pytest.mark.asyncio
async def test_create_row_policy_valid_dsl_compiles():
    session = _session()
    session.get.return_value = Dataset(id=uuid.uuid4(), table_name="customers")
    columns = MagicMock()
    columns.all.return_value = [("region",)]
    session.execute.return_value = columns
    payload = gov.RowPolicyIn(
        dataset_id=uuid.uuid4(), subject_type="role", subject_id=uuid.uuid4(),
        condition_json={"op": "equals", "column": "region", "value": "EMEA"},
    )
    out = await gov.create_row_policy(payload, session, _admin())
    assert "region" in out.sql_condition and "EMEA" in out.sql_condition


@pytest.mark.asyncio
async def test_create_row_policy_invalid_dsl_400():
    session = _session()
    session.get.return_value = Dataset(id=uuid.uuid4(), table_name="customers")
    columns = MagicMock()
    columns.all.return_value = [("region",)]
    session.execute.return_value = columns
    payload = gov.RowPolicyIn(
        dataset_id=uuid.uuid4(), subject_type="role", subject_id=uuid.uuid4(),
        condition_json={"op": "bogus_op"},
    )
    with pytest.raises(HTTPException) as exc:
        await gov.create_row_policy(payload, session, _admin())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_row_policy_bad_subject_type_400():
    session = _session()
    payload = gov.RowPolicyIn(
        dataset_id=uuid.uuid4(), subject_type="banana", subject_id=uuid.uuid4(),
        condition_json={"op": "equals", "column": "x", "value": 1},
    )
    with pytest.raises(HTTPException) as exc:
        await gov.create_row_policy(payload, session, _admin())
    assert exc.value.status_code == 400


# --- column masks ----------------------------------------------------------

@pytest.mark.asyncio
async def test_create_column_mask_unknown_type_400():
    session = _session()
    session.get.return_value = Dataset(id=uuid.uuid4(), table_name="customers")
    payload = gov.ColumnMaskIn(
        dataset_id=uuid.uuid4(), column_name="ssn", subject_type="role",
        subject_id=uuid.uuid4(), mask_type="scramble",
    )
    with pytest.raises(HTTPException) as exc:
        await gov.create_column_mask(payload, session, _admin())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_column_mask_hidden_sets_can_view_false():
    session = _session()
    session.get.return_value = Dataset(id=uuid.uuid4(), table_name="customers")
    payload = gov.ColumnMaskIn(
        dataset_id=uuid.uuid4(), column_name="ssn", subject_type="role",
        subject_id=uuid.uuid4(), mask_type="hidden",
    )
    out = await gov.create_column_mask(payload, session, _admin())
    assert out.mask_type == "hidden"
    # the added ColumnPermission should have can_view False for hidden
    added = session.add.call_args[0][0]
    assert added.can_view is False


# --- secrets ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_secret_out_never_exposes_value():
    # SecretOut has no secret_value field at all.
    assert "secret_value" not in gov.SecretOut.model_fields


@pytest.mark.asyncio
async def test_create_secret_requires_value():
    session = _session()
    payload = gov.SecretIn(name="db", value="")
    with pytest.raises(HTTPException) as exc:
        await gov.create_secret_endpoint(payload, session, _admin())
    assert exc.value.status_code == 400
