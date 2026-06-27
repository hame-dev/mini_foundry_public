from __future__ import annotations

import hashlib
import uuid
import asyncio
from typing import Any

import sqlglot.expressions as exp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.logger import log_event
from app.auth.models import User
from app.cache.sql_cache import cache_key_for_sql, get_cached_result, set_cached_result
from app.data.models import Dataset, DatasetColumn
from app.execution.cancellation import query_registry
from app.execution.sql_runner import pick_engine, run_sql
from app.execution.sql_utils import TableReference, referenced_table_names, referenced_table_refs, table_key
from app.execution.sql_validator import validate_sql
from app.governed_query.rewrite import TableSpec, compile_governed_source_sql
from app.permissions.enforcement import (
    PermissionDenied,
    get_permission_version,
    policy_cache_versions,
    require_object_capability,
)
from app.permissions.masking import apply_masks, resolve_column_masks
from app.permissions.row_policy import resolve_row_policies
from app.platform.service import effective_schema, resolve_dataset_version


def _dataset_schema(ds: Dataset) -> str:
    return (getattr(ds, "schema_name", None) or "public").lower()


def _effective_schema(ds: Dataset) -> str:
    return effective_schema(ds)


def _matches_ref(ds: Dataset, ref: TableReference) -> bool:
    if (getattr(ds, "table_name", "") or "").lower() != ref.table.lower():
        return False
    if ref.schema is None:
        return True
    return _dataset_schema(ds) == ref.schema.lower()


async def resolve_datasets_for_sql(
    session: AsyncSession,
    sql: str,
    explicit_dataset_ids: list[uuid.UUID] | None = None,
) -> list[Dataset]:
    refs = referenced_table_refs(sql)
    explicit: list[Dataset] = []
    if explicit_dataset_ids:
        rows = await session.execute(select(Dataset).where(Dataset.id.in_(explicit_dataset_ids)))
        explicit = list(rows.scalars().all())
        found_ids = {ds.id for ds in explicit}
        missing = [str(dataset_id) for dataset_id in explicit_dataset_ids if dataset_id not in found_ids]
        if missing:
            raise PermissionDenied(f"dataset not found or not accessible: {', '.join(missing)}")
    if not refs:
        return explicit

    table_names = sorted({ref.table.lower() for ref in refs})
    rows = await session.execute(select(Dataset).where(Dataset.table_name.in_(table_names)))
    candidates = list(rows.scalars().all())
    if explicit_dataset_ids:
        allowed_ids = {ds.id for ds in explicit}
        candidates = [ds for ds in candidates if ds.id in allowed_ids]

    candidate_ids = {ds.id for ds in candidates}
    resolved: dict[uuid.UUID, Dataset] = {ds.id: ds for ds in explicit if ds.id in candidate_ids or not refs}
    for ref in refs:
        matches = [ds for ds in candidates if _matches_ref(ds, ref)]
        if not matches:
            qualifier = f"{ref.schema}.{ref.table}" if ref.schema else ref.table
            raise PermissionDenied(f"ungoverned table reference is not allowed: {qualifier}")
        if ref.schema is None and len({(_dataset_schema(ds), ds.table_name.lower()) for ds in matches}) > 1:
            raise PermissionDenied(f"ambiguous dataset table reference requires schema qualification: {ref.table}")
        if len(matches) > 1:
            raise PermissionDenied(f"ambiguous dataset table reference: {ref.qualified_key}")
        resolved[matches[0].id] = matches[0]
    return list(resolved.values())


def _is_constant_expression(node: exp.Expression) -> bool:
    if isinstance(node, exp.Alias):
        return _is_constant_expression(node.this)
    if isinstance(node, (exp.Literal, exp.Null, exp.Boolean)):
        return True
    if isinstance(node, exp.Paren):
        return _is_constant_expression(node.this)
    if isinstance(node, exp.Neg):
        return _is_constant_expression(node.this)
    if isinstance(node, (exp.Add, exp.Sub, exp.Mul, exp.Div)):
        return _is_constant_expression(node.left) and _is_constant_expression(node.right)
    if isinstance(node, exp.Cast):
        return _is_constant_expression(node.this)
    return False


def _is_allowlisted_constant_query(root: exp.Expression) -> bool:
    if not isinstance(root, exp.Select):
        return False
    if list(root.find_all(exp.Table)):
        return False
    if root.args.get("from") or root.args.get("from_") or root.args.get("joins"):
        return False
    expressions = list(root.expressions or [])
    return bool(expressions) and all(_is_constant_expression(item) for item in expressions)


async def _build_governed_rewrite(
    session: AsyncSession,
    user: User,
    sql: str,
    *,
    dataset_ids: list[uuid.UUID] | None = None,
    capability: str = "use_in_sql",
) -> tuple[str, str, list[Dataset], dict[str, str], dict[str, str]]:
    root = validate_sql(sql)
    datasets = await resolve_datasets_for_sql(session, sql, dataset_ids)
    if not datasets and not _is_allowlisted_constant_query(root):
        raise PermissionDenied("query must reference at least one governed dataset")
    for ds in datasets:
        await require_object_capability(session, user, "dataset", ds.id, capability)

    engine = pick_engine(datasets)
    refs = referenced_table_refs(sql)
    table_names = [ref.table.lower() for ref in refs]
    policy_conditions = await resolve_row_policies(session, user.id, table_names, datasets=datasets)
    combined_masks: dict[str, str] = {}
    fallback_masks: dict[str, str] = {}
    specs: dict[str, TableSpec] = {}
    for ds in datasets:
        masks = await resolve_column_masks(session, user.id, ds.id)
        combined_masks.update(masks)
        cols = [
            c[0]
            for c in (
                await session.execute(
                    select(DatasetColumn.name).where(DatasetColumn.dataset_id == ds.id)
                )
            ).all()
        ]
        key = table_key(getattr(ds, "schema_name", None), ds.table_name)
        bare_key = ds.table_name.lower()
        spec = TableSpec(
            table_name=bare_key,
            schema_name=_effective_schema(ds),
            real_table=ds.table_name,
            columns=cols,
            masks=masks,
            rls=policy_conditions.get(key) or policy_conditions.get(bare_key),
        )
        specs[key] = spec
        if bare_key not in specs:
            specs[bare_key] = spec
        if not cols:
            fallback_masks.update(masks)

    rewritten = compile_governed_source_sql(sql, specs, dialect=engine)
    validate_sql(rewritten)
    return rewritten, engine, datasets, combined_masks, fallback_masks


async def prepare_governed_sql(
    session: AsyncSession,
    user: User,
    sql: str,
    *,
    dataset_ids: list[uuid.UUID] | None = None,
    capability: str = "use_in_sql",
) -> str:
    """Permission-check and rewrite SQL without executing it."""
    rewritten, _, _, _, _ = await _build_governed_rewrite(
        session,
        user,
        sql,
        dataset_ids=dataset_ids,
        capability=capability,
    )
    return rewritten


async def _resolve_storage_overrides(
    session: AsyncSession,
    datasets: list[Dataset],
    pinned_versions: dict[uuid.UUID, uuid.UUID] | None,
) -> dict[uuid.UUID, str] | None:
    """Map duckdb datasets to a pinned version's ``storage_uri`` for reproducible
    reads. Returns ``None`` when nothing is pinned."""
    if not pinned_versions:
        return None
    from app.platform.models import DatasetVersion

    overrides: dict[uuid.UUID, str] = {}
    for ds in datasets:
        version_id = pinned_versions.get(ds.id)
        if not version_id or (getattr(ds, "execution_engine", None) or "postgres") != "duckdb":
            continue
        version = await session.get(DatasetVersion, version_id)
        if version is not None and version.storage_uri:
            overrides[ds.id] = version.storage_uri
    return overrides or None


async def _policy_aware_cache_key(
    session: AsyncSession, user: User, sql: str, datasets: list[Dataset], engine: str
) -> str:
    """Build a cache key that captures user, permission/policy versions, branch,
    and the branch-aware dataset versions, so a cached row can never outlive the
    policy or data it was produced under."""
    ids = [ds.id for ds in datasets]
    permission_version = await get_permission_version(session)
    row_version, mask_version = await policy_cache_versions(session, ids)
    version_ids: list[str] = []
    branch = "main"
    for ds in datasets:
        version = await resolve_dataset_version(session, ds.id)
        if version is not None:
            version_ids.append(str(version.id))
        branch = getattr(ds, "branch_name", None) or branch
    return cache_key_for_sql(
        str(user.id),
        sql,
        permission_version,
        dataset_version_ids=sorted(version_ids),
        branch_id=branch,
        engine=engine,
        row_policy_version=row_version,
        mask_policy_version=mask_version,
    )


async def governed_query(
    session: AsyncSession,
    user: User,
    sql: str,
    *,
    params: dict[str, Any] | None = None,
    dataset_ids: list[uuid.UUID] | None = None,
    capability: str = "use_in_sql",
    audit_resource_type: str = "sql",
    audit_resource_id: str | None = None,
    query_id: str | None = None,
    use_cache: bool = False,
    pinned_versions: dict[uuid.UUID, uuid.UUID] | None = None,
) -> dict[str, Any]:
    rewritten, engine, datasets, combined_masks, fallback_masks = await _build_governed_rewrite(
        session,
        user,
        sql,
        dataset_ids=dataset_ids,
        capability=capability,
    )
    # Caching happens *after* ACL/row/mask enforcement above, so a cache hit is
    # still fully authorized; the key embeds the policy/version state.
    cache_key = None
    if use_cache and not params and not pinned_versions:  # no params/pins affect the result
        cache_key = await _policy_aware_cache_key(session, user, sql, datasets, engine)
        cached = await get_cached_result(cache_key)
        if cached is not None:
            cached["cached"] = True
            return cached
    # Pin duckdb reads to the recorded immutable version's storage_uri. Postgres
    # logical datasets have no per-version physical table, so they stay live
    # (the pinned version is still recorded in the audit event below).
    storage_overrides = await _resolve_storage_overrides(session, datasets, pinned_versions)
    if query_id:
        query_registry.register(query_id, owner_id=str(user.id))
    try:
        result = await asyncio.to_thread(
            run_sql, rewritten, params=params, datasets=datasets, query_id=query_id, storage_overrides=storage_overrides
        )
    finally:
        if query_id:
            query_registry.finish(query_id)

    # Defense-in-depth: masks compiled into the projection are already applied;
    # only datasets whose columns were unknown need post-query masking.
    columns = [c for c in result["columns"] if combined_masks.get(c) != "hidden"]
    rows = apply_masks(result["rows"], fallback_masks) if fallback_masks else result["rows"]
    if len(columns) != len(result["columns"]):
        allowed = set(columns)
        rows = [{k: v for k, v in row.items() if k in allowed} for row in rows]

    versions = []
    for ds in datasets:
        version = await resolve_dataset_version(session, ds.id)
        versions.append(
            {
                "dataset_id": str(ds.id),
                "dataset_version_id": str(version.id) if version else None,
                "version_number": version.version_number if version else None,
            }
        )

    query_hash = hashlib.sha256(rewritten.encode()).hexdigest()
    await log_event(
        session,
        user=user,
        event_type="SQL_RUN",
        resource_type=audit_resource_type,
        resource_id=audit_resource_id,
        input_summary={"query_hash": query_hash, "engine": engine, "dataset_versions": versions},
        output_summary={"row_count": len(rows), "columns": columns},
    )
    result_payload = {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "dataset_versions": versions,
        "engine": engine,
        "query_hash": query_hash,
        "rewritten_sql": rewritten,
    }
    if cache_key is not None:
        await set_cached_result(cache_key, result_payload)
    return result_payload


async def governed_dataset_preview(
    session: AsyncSession,
    user: User,
    dataset: Dataset,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    sql = f'SELECT * FROM "{dataset.schema_name}"."{dataset.table_name}" LIMIT {max(1, min(limit, 1000))}'
    try:
        return await governed_query(
            session,
            user,
            sql,
            dataset_ids=[dataset.id],
            capability="view_data",
            audit_resource_type="dataset_preview",
            audit_resource_id=str(dataset.id),
            use_cache=True,
        )
    except PermissionDenied:
        raise
