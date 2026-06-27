"""Functions on Objects — computed-property validation + mask-aware evaluation.

Pure validation cases are exercised directly; the load_object integration mocks
the governed query (matching the unit-test style used across the suite) and
asserts the SQL we hand to the governance layer.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ontology import service
from app.ontology.functions import (
    BadFunctionExpression,
    build_function_select,
    validate_function_expression,
)

COLS = {"id", "first_name", "last_name", "quantity", "unit_price", "created_at"}


def test_valid_expressions_return_referenced_columns():
    assert validate_function_expression("quantity * unit_price", COLS) == {"quantity", "unit_price"}
    assert validate_function_expression("upper(first_name)", COLS) == {"first_name"}
    assert validate_function_expression("extract(year from created_at)", COLS) == {"created_at"}


@pytest.mark.parametrize(
    "expr",
    [
        "(select 1)",                 # subquery
        "quantity * price",           # unknown column
        "pg_read_file(quantity)",     # function not in allowlist
        "*",                          # star
        "other.first_name",           # table-qualified column
        "",                           # empty
    ],
)
def test_unsafe_expressions_rejected(expr):
    with pytest.raises(BadFunctionExpression):
        validate_function_expression(expr, COLS)


def test_build_function_select_redacts_masked_columns():
    specs = [{"name": "total", "expression": "quantity*unit_price", "columns": {"quantity", "unit_price"}}]
    # unit_price masked -> redacted to NULL so the derived value can't leak it
    fragments, names = build_function_select(specs, {"unit_price"})
    assert fragments == ['NULL AS "total"']
    assert names == ["total"]
    # not masked -> the real expression is emitted
    fragments, _ = build_function_select(specs, set())
    assert fragments == ['(quantity*unit_price) AS "total"']


def _obj():
    obj = MagicMock()
    obj.type_name = "Sale"
    obj.dataset_id = uuid.uuid4()
    obj.primary_key = "id"
    obj.display_name_column = None
    obj.properties = [
        {"name": "id", "column": "id"},
        {"name": "quantity", "column": "quantity"},
        {"name": "unit_price", "column": "unit_price"},
    ]
    return obj


def _ds():
    ds = MagicMock()
    ds.id = uuid.uuid4()
    ds.schema_name = "public"
    ds.table_name = "sales"
    return ds


@pytest.mark.asyncio
async def test_load_object_includes_computed_function(monkeypatch):
    obj, ds = _obj(), _ds()
    session = AsyncMock()
    session.get = AsyncMock(return_value=ds)
    user = MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(service, "get_object", AsyncMock(return_value=obj))
    monkeypatch.setattr(service, "require_object_capability", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "resolve_column_masks", AsyncMock(return_value={}))
    monkeypatch.setattr(
        service, "resolve_function_specs",
        AsyncMock(return_value=[{"name": "total", "expression": "quantity*unit_price", "columns": {"quantity", "unit_price"}}]),
    )
    captured = {}

    async def fake_gq(session, user, sql, **kwargs):
        captured["sql"] = sql
        return {"rows": [{"id": "1", "quantity": 2, "unit_price": 5, "total": 10}], "columns": ["id", "quantity", "unit_price", "total"]}

    monkeypatch.setattr(service, "governed_query", fake_gq)

    result = await service.load_object(session, user, "Sale", "1")
    assert '(quantity*unit_price) AS "total"' in captured["sql"]
    assert result["functions"] == {"total": 10}
    assert result["properties"]["quantity"] == 2


@pytest.mark.asyncio
async def test_load_object_redacts_function_over_masked_column(monkeypatch):
    obj, ds = _obj(), _ds()
    session = AsyncMock()
    session.get = AsyncMock(return_value=ds)
    user = MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(service, "get_object", AsyncMock(return_value=obj))
    monkeypatch.setattr(service, "require_object_capability", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "resolve_column_masks", AsyncMock(return_value={"unit_price": "hash"}))
    monkeypatch.setattr(
        service, "resolve_function_specs",
        AsyncMock(return_value=[{"name": "total", "expression": "quantity*unit_price", "columns": {"quantity", "unit_price"}}]),
    )
    captured = {}

    async def fake_gq(session, user, sql, **kwargs):
        captured["sql"] = sql
        return {"rows": [{"id": "1", "quantity": 2, "total": None}], "columns": ["id", "quantity", "total"]}

    monkeypatch.setattr(service, "governed_query", fake_gq)

    result = await service.load_object(session, user, "Sale", "1")
    assert 'NULL AS "total"' in captured["sql"]
    assert '(quantity*unit_price)' not in captured["sql"]
    assert result["functions"] == {"total": None}
