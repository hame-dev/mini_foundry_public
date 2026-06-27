"""DuckDB execution engine for Parquet-backed datasets.

Each call opens an in-memory connection, configures httpfs against the
MinIO endpoint when storage_backend == 's3', registers every duckdb-engine
dataset as a CREATE OR REPLACE VIEW reading from its storage_uri, then
executes the user's SQL.

Identifier safety: dataset table_names go through assert_safe_ident;
the SQL itself was already validated by sqlglot in sql_runner.run_sql.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from app.config import get_settings
from app.execution.cancellation import query_registry
from app.execution.sql_utils import enforce_outer_limit
from app.storage.fs import default_bucket_uri
from app.util.identifiers import assert_safe_ident

if TYPE_CHECKING:
    from app.data.models import Dataset

from app.governed_query.service import _effective_schema


def _reject_external_postgres_on_duckdb_path(datasets: list["Dataset"]) -> None:
    from app.execution.sql_runner import _is_managed_postgres_source

    for ds in datasets:
        source_id = getattr(ds, "source_id", None)
        if source_id and not _is_managed_postgres_source(str(source_id)):
            raise ValueError("Cannot query external postgres datasets on the duckdb execution path")


def _duckdb_string_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _enforce_limit(sql: str, row_limit: int) -> str:
    return enforce_outer_limit(sql, row_limit, dialect="duckdb")


def _configure_httpfs(con) -> None:
    settings = get_settings()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if settings.storage_backend != "s3":
        return
    endpoint = settings.s3_endpoint
    # DuckDB expects host:port without scheme
    endpoint = re.sub(r"^https?://", "", endpoint)
    con.execute(f"SET s3_endpoint={_duckdb_string_literal(endpoint)}")
    con.execute("SET s3_url_style='path'")
    con.execute(f"SET s3_access_key_id={_duckdb_string_literal(settings.s3_access_key)}")
    con.execute(f"SET s3_secret_access_key={_duckdb_string_literal(settings.s3_secret_key)}")
    con.execute("SET s3_use_ssl=false")


def _postgres_attach_dsn(sync_database_url: str) -> str:
    parsed = urlparse(sync_database_url)
    username = parsed.username or ""
    password = parsed.password or ""
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    dbname = parsed.path.lstrip("/")
    return (
        f"host={host} port={port} dbname={dbname} "
        f"user={username} password={password} connect_timeout=5"
    )


def _register_postgres_views(con: Any, datasets: list["Dataset"]) -> None:
    postgres_datasets = [
        ds for ds in datasets
        if (getattr(ds, "execution_engine", None) or "postgres") == "postgres"
    ]
    if not postgres_datasets:
        return
    settings = get_settings()
    con.execute("INSTALL postgres; LOAD postgres;")
    con.execute(
        f"ATTACH {_duckdb_string_literal(_postgres_attach_dsn(settings.readonly_sync_database_url or settings.sync_database_url))} "
        "AS mf_pg (TYPE POSTGRES, READ_ONLY)"
    )
    for ds in postgres_datasets:
        assert_safe_ident(ds.table_name)
        schema = _effective_schema(ds)
        assert_safe_ident(schema)
        con.execute(
            f'CREATE OR REPLACE VIEW "{ds.table_name}" AS '
            f'SELECT * FROM mf_pg."{schema}"."{ds.table_name}"'
        )


def run_duckdb_sql(
    sql: str,
    datasets: list["Dataset"],
    params: dict[str, Any] | None = None,
    *,
    query_id: str | None = None,
    storage_overrides: dict[Any, str] | None = None,
) -> dict[str, Any]:
    import duckdb

    settings = get_settings()
    con = duckdb.connect(":memory:")
    cancel_handle = None
    try:
        _reject_external_postgres_on_duckdb_path(datasets)
        con.execute(f"SET memory_limit='{settings.duckdb_memory_limit}'")
        if settings.duckdb_query_timeout_seconds > 0:
            try:
                con.execute(f"SET statement_timeout='{settings.duckdb_query_timeout_seconds}s'")
            except Exception:
                pass
        _configure_httpfs(con)
        if query_id:
            cancel_handle = query_registry.attach(query_id, lambda: getattr(con, "interrupt", lambda: None)())
            if query_registry.is_cancelled(query_id):
                raise TimeoutError("query cancelled")

        overrides = storage_overrides or {}
        for ds in datasets:
            pinned_uri = overrides.get(getattr(ds, "id", None)) if overrides else None
            if (getattr(ds, "execution_engine", None) or "postgres") != "duckdb" or not (pinned_uri or ds.storage_uri):
                continue
            assert_safe_ident(ds.table_name)
            if pinned_uri:
                # Pinned immutable version takes precedence over the live/branch uri.
                uri = pinned_uri
            else:
                uri = ds.storage_uri
                branch = (getattr(ds, "branch_name", None) or "main")
                if branch != "main":
                    uri = default_bucket_uri(f"datasets/{ds.id}/branches/{branch}/{ds.table_name}.parquet")
            con.execute(
                f'CREATE OR REPLACE VIEW "{ds.table_name}" AS '
                f"SELECT * FROM read_parquet({_duckdb_string_literal(uri)})"
            )
        _register_postgres_views(con, datasets)

        final = _enforce_limit(sql, settings.sql_row_limit)
        result = con.execute(final, params or {})
        columns = [c[0] for c in result.description]
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        return {"columns": columns, "rows": rows, "row_count": len(rows)}
    finally:
        if cancel_handle is not None:
            cancel_handle.close()
        con.close()
