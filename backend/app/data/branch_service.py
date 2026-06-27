"""Physical dataset branching service.

Each branch gets an isolated copy of the source table written into a
PostgreSQL schema named  mf_branch_<branch_name>  (for postgres-engine
datasets) or a separate MinIO prefix
  datasets/<dataset_id>/branches/<branch_name>/
for DuckDB/Parquet datasets.

Lifecycle:
  create_branch  → status=open
  commit_branch  → status=committed
  merge_branch   → status=merged  (copies rows back to parent schema)
  abort_branch   → status=aborted (drops the branch schema/prefix)
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.data.models import BranchTransaction, Dataset
from app.storage.fs import default_bucket_uri, get_fs
from app.storage.parquet import read_parquet, write_parquet
from app.util.identifiers import assert_safe_ident

_SAFE_BRANCH = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def _validate_branch_name(name: str) -> None:
    if not _SAFE_BRANCH.match(name):
        raise ValueError(f"Invalid branch name '{name}'. Use only a-z, A-Z, 0-9, _ or -")


def _pg_schema(branch_name: str) -> str:
    return f"mf_branch_{branch_name.lower().replace('-', '_')}"


def _base_table_name(table_name: str) -> str:
    return f"__mf_base_{table_name}"


def _duckdb_branch_uri(ds: Dataset, branch_name: str, *, base: bool = False) -> str:
    prefix = f"datasets/{ds.id}/branches/{branch_name}"
    if base:
        prefix += "/__base__"
    return default_bucket_uri(f"{prefix}/{ds.table_name}.parquet")


def _copy_uri(src: str, dst: str) -> None:
    src_fs = get_fs(src)
    dst_fs = get_fs(dst)
    parent = dst.rsplit("/", 1)[0]
    if parent and not dst_fs.exists(parent):
        dst_fs.makedirs(parent, exist_ok=True)
    with src_fs.open(src, "rb") as r, dst_fs.open(dst, "wb") as w:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            w.write(chunk)


def _delete_uri_prefix(uri: str) -> None:
    fs = get_fs(uri)
    if fs.exists(uri):
        fs.rm(uri, recursive=True)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

async def create_branch(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    branch_name: str,
    from_branch: str = "main",
    created_by: uuid.UUID | None = None,
) -> BranchTransaction:
    _validate_branch_name(branch_name)

    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise ValueError(f"Dataset {dataset_id} not found")

    existing_q = await session.execute(
        select(BranchTransaction).where(
            BranchTransaction.dataset_id == dataset_id,
            BranchTransaction.branch_name == branch_name,
            BranchTransaction.status.in_(["open", "committed"]),
        )
    )
    if existing_q.scalar_one_or_none():
        raise ValueError(f"Branch '{branch_name}' already exists for this dataset")

    engine = ds.execution_engine or "postgres"

    if engine == "postgres":
        await _create_postgres_branch(ds, branch_name, from_branch)
    elif engine == "duckdb":
        await _create_duckdb_branch(ds, branch_name, from_branch)
    else:
        raise ValueError(f"Branching not supported for engine '{engine}'")

    txn = BranchTransaction(
        dataset_id=dataset_id,
        branch_name=branch_name,
        parent_branch=from_branch,
        status="open",
        created_by=created_by,
    )
    session.add(txn)
    return txn


async def _create_postgres_branch(ds: Dataset, branch_name: str, from_branch: str) -> None:
    from sqlalchemy import create_engine

    assert_safe_ident(ds.table_name)
    src_schema = _pg_schema(from_branch) if from_branch != "main" else ds.schema_name
    dst_schema = _pg_schema(branch_name)
    assert_safe_ident(src_schema)
    assert_safe_ident(dst_schema)

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url)
    with sync_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{dst_schema}"'))
        conn.execute(text(
            f'CREATE TABLE "{dst_schema}"."{ds.table_name}" AS '
            f'SELECT * FROM "{src_schema}"."{ds.table_name}"'
        ))
        conn.execute(text(
            f'CREATE TABLE "{dst_schema}"."{_base_table_name(ds.table_name)}" AS '
            f'SELECT * FROM "{src_schema}"."{ds.table_name}"'
        ))


async def _create_duckdb_branch(ds: Dataset, branch_name: str, from_branch: str) -> None:
    if not ds.storage_uri:
        raise ValueError("Cannot branch a DuckDB dataset without a storage_uri")

    src_uri = ds.storage_uri if from_branch == "main" else _duckdb_branch_uri(ds, from_branch)
    _copy_uri(src_uri, _duckdb_branch_uri(ds, branch_name))
    _copy_uri(src_uri, _duckdb_branch_uri(ds, branch_name, base=True))


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

async def commit_branch(
    session: AsyncSession,
    transaction_id: uuid.UUID,
) -> BranchTransaction:
    txn = await session.get(BranchTransaction, transaction_id)
    if txn is None:
        raise ValueError(f"BranchTransaction {transaction_id} not found")
    if txn.status != "open":
        raise ValueError(f"Cannot commit a branch in status '{txn.status}'")
    txn.status = "committed"
    txn.updated_at = datetime.utcnow()
    return txn


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

async def merge_branch(
    session: AsyncSession,
    transaction_id: uuid.UUID,
    target_branch: str = "main",
) -> dict[str, Any]:
    txn = await session.get(BranchTransaction, transaction_id)
    if txn is None:
        raise ValueError(f"BranchTransaction {transaction_id} not found")
    if txn.status not in ("open", "committed"):
        raise ValueError(f"Cannot merge a branch in status '{txn.status}'")

    ds = await session.get(Dataset, txn.dataset_id)
    if ds is None:
        raise ValueError("Dataset not found")

    engine = ds.execution_engine or "postgres"
    report: dict[str, Any] = {}

    if engine == "postgres":
        report = await _merge_postgres_branch(ds, txn.branch_name, target_branch)
    elif engine == "duckdb":
        report = await _merge_duckdb_branch(ds, txn.branch_name, target_branch)
    else:
        raise ValueError(f"Merging not supported for engine '{engine}'")

    if report.get("status") == "ok":
        txn.status = "merged"
        txn.merged_into = target_branch
        txn.updated_at = datetime.utcnow()
    return report


async def _merge_postgres_branch(ds: Dataset, branch_name: str, target_branch: str) -> dict[str, Any]:
    from sqlalchemy import create_engine

    assert_safe_ident(ds.table_name)
    src_schema = _pg_schema(branch_name)
    dst_schema = _pg_schema(target_branch) if target_branch != "main" else ds.schema_name
    base_table = _base_table_name(ds.table_name)
    assert_safe_ident(src_schema)
    assert_safe_ident(dst_schema)
    assert_safe_ident(base_table)

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url)
    with sync_engine.begin() as conn:
        def _columns(schema: str, table: str) -> list[tuple[str, str, str, str]]:
            return conn.execute(text(
                "SELECT column_name, data_type, udt_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"
            ), {"s": schema, "t": table}).all()

        src_meta = _columns(src_schema, ds.table_name)
        dst_meta = _columns(dst_schema, ds.table_name)
        base_meta = _columns(src_schema, base_table)
        if not src_meta:
            return {"status": "conflict", "message": "branch table not found"}
        if not base_meta:
            return {
                "status": "conflict",
                "message": "branch base snapshot missing; refusing destructive merge",
            }

        src_cols = [row[0] for row in src_meta]
        dst_cols = [row[0] for row in dst_meta]
        if src_meta != dst_meta or src_meta != base_meta:
            return {
                "status": "conflict",
                "schema_conflict": True,
                "source_schema": [dict(zip(["name", "data_type", "udt_name", "is_nullable"], row)) for row in src_meta],
                "target_schema": [dict(zip(["name", "data_type", "udt_name", "is_nullable"], row)) for row in dst_meta],
                "base_schema": [dict(zip(["name", "data_type", "udt_name", "is_nullable"], row)) for row in base_meta],
            }

        common_cols = ", ".join(f'"{c}"' for c in src_cols)
        changed_target = conn.execute(text(
            f'SELECT {common_cols} FROM "{dst_schema}"."{ds.table_name}" '
            f'EXCEPT SELECT {common_cols} FROM "{src_schema}"."{base_table}" LIMIT 100'
        )).all()
        changed_base = conn.execute(text(
            f'SELECT {common_cols} FROM "{src_schema}"."{base_table}" '
            f'EXCEPT SELECT {common_cols} FROM "{dst_schema}"."{ds.table_name}" LIMIT 100'
        )).all()
        if changed_target or changed_base:
            return {
                "status": "conflict",
                "message": "target branch changed since this branch was created",
                "target_added_or_changed_count_sample": len(changed_target),
                "target_removed_count_sample": len(changed_base),
            }

        src_count = conn.execute(text(
            f'SELECT COUNT(*) FROM "{src_schema}"."{ds.table_name}"'
        )).scalar()
        added_count = conn.execute(text(
            f'SELECT COUNT(*) FROM (SELECT {common_cols} FROM "{src_schema}"."{ds.table_name}" '
            f'EXCEPT SELECT {common_cols} FROM "{src_schema}"."{base_table}") AS added'
        )).scalar()
        removed_count = conn.execute(text(
            f'SELECT COUNT(*) FROM (SELECT {common_cols} FROM "{src_schema}"."{base_table}" '
            f'EXCEPT SELECT {common_cols} FROM "{src_schema}"."{ds.table_name}") AS removed'
        )).scalar()
        predicates = " AND ".join(f't."{c}" IS NOT DISTINCT FROM removed."{c}"' for c in src_cols)
        conn.execute(text(
            f'DELETE FROM "{dst_schema}"."{ds.table_name}" AS t '
            f'USING (SELECT {common_cols} FROM "{src_schema}"."{base_table}" '
            f'EXCEPT SELECT {common_cols} FROM "{src_schema}"."{ds.table_name}") AS removed '
            f'WHERE {predicates}'
        ))
        conn.execute(text(
            f'INSERT INTO "{dst_schema}"."{ds.table_name}" ({common_cols}) '
            f'SELECT {common_cols} FROM "{src_schema}"."{ds.table_name}" '
            f'EXCEPT SELECT {common_cols} FROM "{src_schema}"."{base_table}"'
        ))
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{src_schema}" CASCADE'))

    return {
        "status": "ok",
        "rows_merged": src_count,
        "added_rows": added_count,
        "removed_rows": removed_count,
        "target_branch": target_branch,
    }


async def _merge_duckdb_branch(ds: Dataset, branch_name: str, target_branch: str) -> dict[str, Any]:
    if not ds.storage_uri:
        return {"status": "conflict", "message": "DuckDB dataset has no storage_uri"}
    src_uri = _duckdb_branch_uri(ds, branch_name)
    base_uri = _duckdb_branch_uri(ds, branch_name, base=True)
    dst_uri = ds.storage_uri if target_branch == "main" else _duckdb_branch_uri(ds, target_branch)

    try:
        base_df = read_parquet(base_uri)
        branch_df = read_parquet(src_uri)
        target_df = read_parquet(dst_uri)
    except Exception as e:  # noqa: BLE001
        return {"status": "conflict", "message": f"unable to read branch parquet files: {e}"}

    if list(base_df.dtypes.astype(str).items()) != list(branch_df.dtypes.astype(str).items()) or list(base_df.dtypes.astype(str).items()) != list(target_df.dtypes.astype(str).items()):
        return {
            "status": "conflict",
            "schema_conflict": True,
            "base_schema": {c: str(t) for c, t in base_df.dtypes.items()},
            "branch_schema": {c: str(t) for c, t in branch_df.dtypes.items()},
            "target_schema": {c: str(t) for c, t in target_df.dtypes.items()},
        }

    if not target_df.equals(base_df):
        return {
            "status": "conflict",
            "message": "target branch changed since this branch was created",
        }

    write_parquet(branch_df, dst_uri)
    _delete_uri_prefix(default_bucket_uri(f"datasets/{ds.id}/branches/{branch_name}"))
    return {"status": "ok", "rows_merged": int(len(branch_df)), "target_branch": target_branch}


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

async def diff_branch(
    session: AsyncSession,
    transaction_id: uuid.UUID,
) -> dict[str, Any]:
    txn = await session.get(BranchTransaction, transaction_id)
    if txn is None:
        raise ValueError(f"BranchTransaction {transaction_id} not found")

    ds = await session.get(Dataset, txn.dataset_id)
    if ds is None:
        raise ValueError("Dataset not found")

    engine = ds.execution_engine or "postgres"
    if engine != "postgres":
        return {"status": "unsupported", "message": "Diff only supported for postgres-engine datasets"}

    return await _diff_postgres(ds, txn.branch_name, txn.parent_branch)


async def _diff_postgres(ds: Dataset, branch_name: str, parent_branch: str) -> dict[str, Any]:
    from sqlalchemy import create_engine

    assert_safe_ident(ds.table_name)
    branch_schema = _pg_schema(branch_name)
    parent_schema = _pg_schema(parent_branch) if parent_branch != "main" else ds.schema_name
    assert_safe_ident(branch_schema)
    assert_safe_ident(parent_schema)

    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url)
    with sync_engine.connect() as conn:
        cols_q = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"
        ), {"s": branch_schema, "t": ds.table_name})
        cols = [r[0] for r in cols_q]

        if not cols:
            return {"status": "error", "message": "Branch table not found"}

        col_list = ", ".join(f'"{c}"' for c in cols)

        added = conn.execute(text(
            f'SELECT {col_list} FROM "{branch_schema}"."{ds.table_name}" '
            f'EXCEPT SELECT {col_list} FROM "{parent_schema}"."{ds.table_name}" LIMIT 500'
        ))
        added_rows = [dict(zip(cols, r)) for r in added]

        removed = conn.execute(text(
            f'SELECT {col_list} FROM "{parent_schema}"."{ds.table_name}" '
            f'EXCEPT SELECT {col_list} FROM "{branch_schema}"."{ds.table_name}" LIMIT 500'
        ))
        removed_rows = [dict(zip(cols, r)) for r in removed]

    return {
        "status": "ok",
        "columns": cols,
        "added": added_rows,
        "removed": removed_rows,
        "added_count": len(added_rows),
        "removed_count": len(removed_rows),
    }


# ---------------------------------------------------------------------------
# Abort
# ---------------------------------------------------------------------------

async def abort_branch(
    session: AsyncSession,
    transaction_id: uuid.UUID,
) -> BranchTransaction:
    txn = await session.get(BranchTransaction, transaction_id)
    if txn is None:
        raise ValueError(f"BranchTransaction {transaction_id} not found")
    if txn.status not in ("open", "committed"):
        raise ValueError(f"Cannot abort a branch in status '{txn.status}'")

    ds = await session.get(Dataset, txn.dataset_id)
    if ds:
        engine = ds.execution_engine or "postgres"
        if engine == "postgres":
            await _drop_postgres_branch(ds, txn.branch_name)
        elif engine == "duckdb":
            await _drop_duckdb_branch(ds, txn.branch_name)

    txn.status = "aborted"
    txn.updated_at = datetime.utcnow()
    return txn


async def _drop_postgres_branch(ds: Dataset, branch_name: str) -> None:
    from sqlalchemy import create_engine

    schema = _pg_schema(branch_name)
    assert_safe_ident(schema)
    settings = get_settings()
    sync_engine = create_engine(settings.sync_database_url)
    with sync_engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


async def _drop_duckdb_branch(ds: Dataset, branch_name: str) -> None:
    _delete_uri_prefix(default_bucket_uri(f"datasets/{ds.id}/branches/{branch_name}"))


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

async def list_branches(
    session: AsyncSession,
    dataset_id: uuid.UUID,
) -> list[BranchTransaction]:
    q = await session.execute(
        select(BranchTransaction)
        .where(BranchTransaction.dataset_id == dataset_id)
        .order_by(BranchTransaction.created_at.desc())
    )
    return list(q.scalars().all())
