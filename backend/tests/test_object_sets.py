"""Object Sets — structured-filter compilation + governed execution.

The filter compiler is tested directly; query_object_set mocks the governed
query (matching the suite's unit-test style) and asserts that the assembled SQL
is routed through the governance layer with the right capability, that filters
are parameterized, and that masked columns can't leak through computed values.
Visibility (ACL) is tested via the router helper.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ontology import object_sets, service
from app.ontology.object_sets import BadFilter, build_filter_where
from app.permissions.enforcement import PermissionDenied

ALLOWED = {"id", "status", "amount", "region"}


def test_build_filter_where_binary_and_params():
    where, params = build_filter_where(
        [{"column": "status", "op": "eq", "value": "active"},
         {"column": "amount", "op": "gte", "value": 100}],
        ALLOWED,
    )
    assert where == '"status" = :p0 AND "amount" >= :p1'
    assert params == {"p0": "active", "p1": 100}


def test_build_filter_where_in_and_null():
    where, params = build_filter_where(
        [{"column": "region", "op": "in", "value": ["us", "eu"]},
         {"column": "amount", "op": "is_null"}],
        ALLOWED,
    )
    assert where == '"region" IN (:p0_0, :p0_1) AND "amount" IS NULL'
    assert params == {"p0_0": "us", "p0_1": "eu"}


def test_build_filter_where_empty():
    assert build_filter_where([], ALLOWED) == ("", {})


def test_build_filter_where_rejects_unknown_column():
    with pytest.raises(BadFilter, match="disallowed column"):
        build_filter_where([{"column": "secret", "op": "eq", "value": 1}], ALLOWED)


def test_build_filter_where_rejects_unknown_operator():
    with pytest.raises(BadFilter, match="unknown operator"):
        build_filter_where([{"column": "status", "op": "regex", "value": ".*"}], ALLOWED)


def _obj():
    obj = MagicMock()
    obj.type_name = "Order"
    obj.dataset_id = uuid.uuid4()
    obj.primary_key = "id"
    obj.display_name_column = None
    obj.properties = [
        {"name": "id", "column": "id"},
        {"name": "status", "column": "status"},
        {"name": "amount", "column": "amount"},
    ]
    return obj


def _ds():
    ds = MagicMock()
    ds.id = uuid.uuid4()
    ds.schema_name = "public"
    ds.table_name = "orders"
    return ds


def _patch_common(monkeypatch, obj, ds, masks=None, fn_specs=None):
    session = AsyncMock()
    session.get = AsyncMock(return_value=ds)
    monkeypatch.setattr(service, "get_object", AsyncMock(return_value=obj))
    monkeypatch.setattr(object_sets, "resolve_column_masks", AsyncMock(return_value=masks or {}))
    monkeypatch.setattr(object_sets, "resolve_function_specs", AsyncMock(return_value=fn_specs or []))
    return session


@pytest.mark.asyncio
async def test_query_object_set_routes_through_governance(monkeypatch):
    obj, ds = _obj(), _ds()
    session = _patch_common(monkeypatch, obj, ds)
    user = MagicMock(id=uuid.uuid4())
    captured = {}

    async def fake_gq(session, user, sql, **kwargs):
        captured["sql"] = sql
        captured["params"] = kwargs.get("params")
        captured["capability"] = kwargs.get("capability")
        captured["audit_resource_type"] = kwargs.get("audit_resource_type")
        return {"rows": [{"id": "1", "status": "active", "amount": 50}],
                "columns": ["id", "status", "amount"], "dataset_versions": []}

    monkeypatch.setattr(object_sets, "governed_query", fake_gq)

    result = await object_sets.query_object_set(
        session, user, "Order", [{"column": "status", "op": "eq", "value": "active"}], limit=10,
    )
    assert captured["capability"] == "view_data"
    assert captured["audit_resource_type"] == "ontology_object_set"
    assert 'WHERE "status" = :p0' in captured["sql"]
    assert captured["params"]["p0"] == "active"
    assert captured["params"]["__limit"] == 10
    assert result["objects"] == [{"id": "1", "display_name": None, "properties": {"id": "1", "status": "active", "amount": 50}, "functions": {}}]


@pytest.mark.asyncio
async def test_query_object_set_redacts_masked_function(monkeypatch):
    obj, ds = _obj(), _ds()
    session = _patch_common(
        monkeypatch, obj, ds,
        masks={"amount": "hash"},
        fn_specs=[{"name": "doubled", "expression": "amount*2", "columns": {"amount"}}],
    )
    user = MagicMock(id=uuid.uuid4())
    captured = {}

    async def fake_gq(session, user, sql, **kwargs):
        captured["sql"] = sql
        return {"rows": [], "columns": [], "dataset_versions": []}

    monkeypatch.setattr(object_sets, "governed_query", fake_gq)
    await object_sets.query_object_set(session, user, "Order", [], limit=5)
    assert 'NULL AS "doubled"' in captured["sql"]


@pytest.mark.asyncio
async def test_query_object_set_propagates_permission_denied(monkeypatch):
    obj, ds = _obj(), _ds()
    session = _patch_common(monkeypatch, obj, ds)
    user = MagicMock(id=uuid.uuid4())
    monkeypatch.setattr(object_sets, "governed_query", AsyncMock(side_effect=PermissionDenied("missing capability: view_data")))
    with pytest.raises(PermissionDenied):
        await object_sets.query_object_set(session, user, "Order", [], limit=5)


@pytest.mark.asyncio
async def test_query_object_set_rejects_unsafe_filter_column(monkeypatch):
    obj, ds = _obj(), _ds()
    session = _patch_common(monkeypatch, obj, ds)
    user = MagicMock(id=uuid.uuid4())
    monkeypatch.setattr(object_sets, "governed_query", AsyncMock(return_value={"rows": [], "columns": [], "dataset_versions": []}))
    with pytest.raises(BadFilter):
        await object_sets.query_object_set(session, user, "Order", [{"column": "ssn", "op": "eq", "value": "x"}], limit=5)


@pytest.mark.asyncio
async def test_object_set_visibility_hides_other_users_private_set(monkeypatch):
    from app.ontology import router

    owner_id = uuid.uuid4()
    s = MagicMock(id=uuid.uuid4(), owner_id=owner_id)
    other = MagicMock(id=uuid.uuid4())
    session = AsyncMock()

    monkeypatch.setattr(router, "effective_capabilities_for_object", AsyncMock(return_value=set()))
    assert await router._object_set_visible(session, other, s) is False

    # owner always sees their own set
    owner = MagicMock(id=owner_id)
    assert await router._object_set_visible(session, owner, s) is True

    # a viewer with an explicit ACL grant can see it
    monkeypatch.setattr(router, "effective_capabilities_for_object", AsyncMock(return_value={"view_metadata"}))
    assert await router._object_set_visible(session, other, s) is True
