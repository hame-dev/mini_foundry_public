"""Governance guards on ontology writeback (Phase 0 hardening).

These exercise the two authorization checks added to ``execute_writeback`` that
run before any database mutation:
  1. the caller must hold writeback/edit/manage on the *target dataset*;
  2. the caller cannot write to a column they have masked/hidden.
Both are pure-control-flow checks, so the DB session and policy resolvers are
mocked (matching the unit-test style used across the suite).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ontology.writeback import execute_writeback
from app.permissions.enforcement import PermissionDenied


def _obj():
    obj = MagicMock()
    obj.type_name = "Customer"
    obj.dataset_id = uuid.uuid4()
    obj.primary_key = "id"
    obj.properties = [
        {"name": "id", "column": "id"},
        {"name": "salary", "column": "salary"},
    ]
    return obj


def _dataset():
    ds = MagicMock()
    ds.id = uuid.uuid4()
    ds.schema_name = "public"
    ds.table_name = "customers"
    ds.branch_name = "main"
    return ds


def _session(obj, ds):
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=obj))
    )
    session.get = AsyncMock(return_value=ds)
    return session


@pytest.fixture(autouse=True)
def _patch_validation(monkeypatch):
    monkeypatch.setattr(
        "app.ontology.validation.validate_action_input", lambda action, params: []
    )
    monkeypatch.setattr(
        "app.ontology.writeback.resolve_row_policies", AsyncMock(return_value={})
    )


@pytest.mark.asyncio
async def test_writeback_denied_without_target_capability(monkeypatch):
    obj, ds = _obj(), _dataset()
    session = _session(obj, ds)
    user = MagicMock(id=uuid.uuid4())
    action = MagicMock(object_type="Customer", change_type="update")

    monkeypatch.setattr(
        "app.permissions.enforcement.effective_capabilities_for_object",
        AsyncMock(return_value=set()),  # no caps on target dataset
    )

    with pytest.raises(PermissionDenied, match="writeback"):
        await execute_writeback(session, user, action, {"id": "1", "salary": "999"})


@pytest.mark.asyncio
async def test_writeback_blocks_masked_column(monkeypatch):
    obj, ds = _obj(), _dataset()
    session = _session(obj, ds)
    user = MagicMock(id=uuid.uuid4())
    action = MagicMock(object_type="Customer", change_type="update")

    monkeypatch.setattr(
        "app.permissions.enforcement.effective_capabilities_for_object",
        AsyncMock(return_value={"writeback"}),
    )
    monkeypatch.setattr(
        "app.ontology.writeback.resolve_column_masks",
        AsyncMock(return_value={"salary": "partial"}),
    )

    with pytest.raises(ValueError, match="masked/unauthorized column: salary"):
        await execute_writeback(session, user, action, {"id": "1", "salary": "999"})
