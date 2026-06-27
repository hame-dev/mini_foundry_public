"""Resolve a dashboard component's data_binding into {columns, rows}.

Reuses the existing SQL validator + read-only runner + column masking + permission
enforcement. Filter values from the dashboard FilterBar are passed as bind
parameters (`:name`), never string-concatenated.
"""
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.data.models import Dataset
from app.dashboards.models import SavedQuery
from app.execution.sql_runner import pick_engine
from app.execution.sql_validator import SqlValidationError
from app.governed_query.service import governed_query, resolve_datasets_for_sql
from app.permissions.enforcement import (
    PermissionDenied,
    require_object_capability,
)
from app.util.identifiers import UnsafeIdentifier, quote_ident
from app.platform.service import latest_dataset_version


_AGGREGATIONS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


class BindingResolutionError(ValueError):
    pass


def _q(ident: str) -> str:
    try:
        return quote_ident(ident)
    except UnsafeIdentifier as e:
        raise BindingResolutionError(str(e))


def build_dataset_transform_sql(
    schema: str, table: str, group_by: list[str], metrics: list[dict], where: str | None
) -> str:
    """Translate a {group_by, metrics, where} spec into a SELECT.

    metrics: list of {column: str, aggregation: "count|sum|avg|min|max", alias: str}.
    Identifiers are validated against [A-Za-z_][A-Za-z0-9_]* before quoting.
    The optional `where` is a clause string; the final SQL is still pushed
    through validate_sql, which will reject any non-SELECT shape.
    """
    select_parts: list[str] = []
    for col in group_by:
        select_parts.append(_q(col))

    for m in metrics:
        agg = (m.get("aggregation") or "count").upper()
        if agg not in _AGGREGATIONS:
            raise BindingResolutionError(f"unsupported aggregation: {agg}")
        col = m.get("column") or "*"
        col_sql = "*" if col == "*" else _q(col)
        alias = m.get("alias") or f"{agg.lower()}_{col if col != '*' else 'all'}"
        select_parts.append(f"{agg}({col_sql}) AS {_q(alias)}")

    if not select_parts:
        select_parts = ["*"]

    sql = f"SELECT {', '.join(select_parts)} FROM {_q(schema)}.{_q(table)}"
    if where:
        sql += f" WHERE {where}"
    if group_by:
        sql += " GROUP BY " + ", ".join(_q(c) for c in group_by)
    return sql


async def _check_dataset_perms(
    session: AsyncSession, user: User, dataset_ids: list[uuid.UUID], capability: str
) -> None:
    for did in dataset_ids:
        ds = await session.get(Dataset, did)
        if ds is None:
            raise BindingResolutionError(f"dataset {did} not found")
        try:
            await require_object_capability(session, user, "dataset", did, capability)
        except PermissionDenied as e:
            raise PermissionDenied(f"dataset {did}: {e}")


async def resolve_binding(
    session: AsyncSession,
    user: User,
    binding: dict[str, Any] | None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Returns {columns: list[str], rows: list[dict]}.

    Raises PermissionDenied for permission errors (caller maps to a per-component
    error slot). Other errors propagate as BindingResolutionError / SqlValidationError.
    """
    if binding is None:
        return {"columns": [], "rows": []}

    btype = binding.get("type")
    filters = filters or {}

    if btype == "static":
        rows = list(binding.get("rows", []))
        cols = list(rows[0].keys()) if rows else []
        return {"columns": cols, "rows": rows, "dataset_versions": [], "engine": "static", "query_hash": None}

    if btype == "sql_query":
        sql: str = binding["sql"]
        dataset_ids = [uuid.UUID(s) for s in binding.get("dataset_ids", [])]
        await _check_dataset_perms(session, user, dataset_ids, "can_use_in_sql")
        result = await governed_query(
            session,
            user,
            sql,
            params=_filter_params(binding.get("params"), filters),
            dataset_ids=dataset_ids,
            audit_resource_type="dashboard_widget",
            use_cache=True,
        )
        return {
            "columns": result["columns"],
            "rows": result["rows"],
            "dataset_versions": result.get("dataset_versions", []),
            "engine": result.get("engine"),
            "query_hash": result.get("query_hash"),
        }

    if btype == "dataset":
        dataset_id = uuid.UUID(binding["dataset_id"])
        ds = await session.get(Dataset, dataset_id)
        if ds is None:
            raise BindingResolutionError(f"dataset {dataset_id} not found")
        try:
            await require_object_capability(session, user, "dataset", dataset_id, "view_data")
        except PermissionDenied as e:
            raise PermissionDenied(f"dataset {dataset_id}: {e}")
        sql = build_dataset_transform_sql(
            schema=ds.schema_name,
            table=ds.table_name,
            group_by=binding.get("group_by", []) or [],
            metrics=binding.get("metrics", []) or [],
            where=binding.get("where"),
        )
        result = await governed_query(
            session,
            user,
            sql,
            params=_filter_params(binding.get("params"), filters),
            dataset_ids=[dataset_id],
            capability="view_data",
            audit_resource_type="dashboard_widget",
            use_cache=True,
        )
        return {
            "columns": result["columns"],
            "rows": result["rows"],
            "dataset_versions": result.get("dataset_versions", []),
            "engine": result.get("engine"),
            "query_hash": result.get("query_hash"),
        }

    if btype == "saved_query":
        sq_id = uuid.UUID(binding["id"])
        sq = await session.get(SavedQuery, sq_id)
        if sq is None:
            raise BindingResolutionError(f"saved_query {sq_id} not found")
        await _check_dataset_perms(session, user, list(sq.dataset_ids), "can_use_in_sql")
        result = await governed_query(
            session,
            user,
            sq.sql,
            params=_filter_params(binding.get("params"), filters),
            dataset_ids=list(sq.dataset_ids),
            audit_resource_type="dashboard_widget",
            audit_resource_id=str(sq.id),
            use_cache=True,
        )
        return {
            "columns": result["columns"],
            "rows": result["rows"],
            "dataset_versions": result.get("dataset_versions", []),
            "engine": result.get("engine"),
            "query_hash": result.get("query_hash"),
        }

    raise BindingResolutionError(f"unknown binding type: {btype!r}")


async def binding_cache_context(
    session: AsyncSession,
    binding: dict[str, Any] | None,
) -> dict[str, Any]:
    if not binding or binding.get("type") == "static":
        return {"dataset_versions": [], "engine": "static", "branch": "main"}

    datasets: list[Dataset] = []
    btype = binding.get("type")
    if btype == "dataset":
        ds = await session.get(Dataset, uuid.UUID(binding["dataset_id"]))
        datasets = [ds] if ds else []
    elif btype == "saved_query":
        sq = await session.get(SavedQuery, uuid.UUID(binding["id"]))
        if sq:
            rows = await session.execute(select(Dataset).where(Dataset.id.in_(list(sq.dataset_ids))))
            datasets = list(rows.scalars().all())
    elif btype == "sql_query":
        datasets = await resolve_datasets_for_sql(
            session,
            binding.get("sql") or "",
            [uuid.UUID(s) for s in binding.get("dataset_ids", [])],
        )
    else:
        return {"dataset_versions": [], "engine": "unknown", "branch": "main"}

    versions = []
    branches = set()
    for ds in datasets:
        version = await latest_dataset_version(session, ds.id)
        branches.add(getattr(version, "branch_name", None) or getattr(ds, "branch_name", None) or "main")
        versions.append(
            {
                "dataset_id": str(ds.id),
                "dataset_version_id": str(version.id) if version else None,
                "version_number": version.version_number if version else None,
            }
        )
    return {
        "dataset_versions": versions,
        "engine": pick_engine(datasets),
        "branch": ",".join(sorted(branches)) if branches else "main",
    }


def _filter_params(declared: list[str] | None, filters: dict[str, Any]) -> dict[str, Any]:
    """Take only the params the binding declared it would consume, so a stray
    filter from another component doesn't accidentally bind."""
    if not declared:
        return {}
    return {k: filters.get(k) for k in declared if k in filters}


__all__ = [
    "BindingResolutionError",
    "binding_cache_context",
    "build_dataset_transform_sql",
    "resolve_binding",
    "SqlValidationError",
]
