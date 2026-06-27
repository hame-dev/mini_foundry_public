"""Object Sets — saved, governed, filterable collections of objects.

Filters are *structured predicates* (``{column, op, value}``), never raw SQL:
columns are validated against the object type's declared column allowlist and
values are always bound parameters. The assembled SELECT (with any computed
properties spliced in) is executed through ``governed_query`` so ResourceACL,
row policies, column masks, versioning, caching, and audit all apply.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.data.models import Dataset
from app.governed_query.service import governed_query
from app.ontology import service
from app.ontology.functions import build_function_select, resolve_function_specs
from app.permissions.masking import resolve_column_masks
from app.util.identifiers import UnsafeIdentifier, assert_safe_ident, quote_ident

MAX_LIMIT = 1000

# op -> (sql template using {col} and bound param, takes_value)
_BINARY_OPS = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "like": "LIKE",
    "ilike": "ILIKE",
}
_NULLARY_OPS = {"is_null": "IS NULL", "not_null": "IS NOT NULL"}


class BadFilter(ValueError):
    pass


def build_filter_where(
    filters: list[dict], allowed: set[str]
) -> tuple[str, dict[str, Any]]:
    """Compile structured predicates into a parameterized WHERE clause.

    Returns ``("", {})`` when there are no filters. Every column is checked
    against ``allowed`` and every value is bound (``:pN``)."""
    if not filters:
        return "", {}
    clauses: list[str] = []
    params: dict[str, Any] = {}
    for i, pred in enumerate(filters):
        col = pred.get("column")
        op = pred.get("op")
        if col not in allowed:
            raise BadFilter(f"unknown or disallowed column: {col!r}")
        try:
            assert_safe_ident(col)
        except UnsafeIdentifier as e:
            raise BadFilter(str(e)) from e
        qcol = quote_ident(col)
        if op in _NULLARY_OPS:
            clauses.append(f"{qcol} {_NULLARY_OPS[op]}")
        elif op == "in":
            values = pred.get("value")
            if not isinstance(values, list) or not values:
                raise BadFilter("'in' requires a non-empty list value")
            keys = []
            for j, v in enumerate(values):
                key = f"p{i}_{j}"
                params[key] = v
                keys.append(f":{key}")
            clauses.append(f"{qcol} IN ({', '.join(keys)})")
        elif op in _BINARY_OPS:
            key = f"p{i}"
            params[key] = pred.get("value")
            clauses.append(f"{qcol} {_BINARY_OPS[op]} :{key}")
        else:
            raise BadFilter(f"unknown operator: {op!r}")
    return " AND ".join(clauses), params


async def query_object_set(
    session: AsyncSession,
    user: User,
    object_type: str,
    filters: list[dict],
    *,
    limit: int = 100,
    offset: int = 0,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    audit_resource_id: str | None = None,
) -> dict[str, Any]:
    """Run a (saved or ad-hoc) object set and return governed, projected rows."""
    obj = await service.get_object(session, object_type)
    if obj is None:
        raise service.OntologyNotFound(f"unknown object type: {object_type}")
    ds = await session.get(Dataset, obj.dataset_id)
    if ds is None:
        raise service.OntologyNotFound(f"backing dataset missing for {object_type}")

    assert_safe_ident(ds.schema_name)
    assert_safe_ident(ds.table_name)

    allowed = service.allowed_columns(obj)
    where, params = build_filter_where(filters or [], allowed)

    masks = await resolve_column_masks(session, user.id, ds.id)
    fn_specs = await resolve_function_specs(session, object_type, allowed)
    fn_fragments, fn_names = build_function_select(fn_specs, set(masks.keys()))

    select_list = "*"
    if fn_fragments:
        select_list = "*, " + ", ".join(fn_fragments)

    sql = f"SELECT {select_list} FROM {quote_ident(ds.schema_name)}.{quote_ident(ds.table_name)}"
    if where:
        sql += f" WHERE {where}"
    if sort_by is not None:
        if sort_by not in allowed and sort_by not in fn_names:
            raise BadFilter(f"cannot sort by unknown column: {sort_by!r}")
        assert_safe_ident(sort_by)
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
        sql += f" ORDER BY {quote_ident(sort_by)} {direction}"

    clamped = max(1, min(int(limit), MAX_LIMIT))
    params["__limit"] = clamped
    params["__offset"] = max(0, int(offset))
    sql += " LIMIT :__limit OFFSET :__offset"

    result = await governed_query(
        session,
        user,
        sql,
        params=params,
        dataset_ids=[ds.id],
        capability="view_data",
        audit_resource_type="ontology_object_set",
        audit_resource_id=audit_resource_id or str(obj.id),
    )

    fn_name_set = set(fn_names)
    objects = []
    for row in result["rows"]:
        objects.append(
            {
                "id": row.get(obj.primary_key),
                "display_name": row.get(obj.display_name_column) if obj.display_name_column else None,
                "properties": service._project(row, obj.properties or []),
                "functions": {n: row.get(n) for n in fn_name_set if n in row},
            }
        )
    return {
        "object_type": object_type,
        "objects": objects,
        "row_count": len(objects),
        "columns": result["columns"],
        "dataset_versions": result["dataset_versions"],
    }
