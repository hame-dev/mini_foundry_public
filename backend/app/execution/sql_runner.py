"""Read-only SQL runner with engine routing.

In v0.8 we route by `dataset.execution_engine`:
- `postgres` (default) → the mini_foundry DB
- `duckdb`             → duckdb_runner over Parquet
- `spark`              → SparkRunner (NotImplementedError until configured)

Mixed engines in a single query are rejected. Callers pass the list of
referenced Dataset rows so the router can pick.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine, text

from app.config import get_settings
from app.execution.cancellation import query_registry
from app.execution.sql_utils import enforce_outer_limit
from app.execution.sql_validator import validate_sql

if TYPE_CHECKING:
    from app.data.models import Dataset


def _enforce_limit(sql: str, row_limit: int) -> str:
    return enforce_outer_limit(sql, row_limit, dialect="postgres")


def _get_datasource_sync(source_id: str) -> dict[str, Any] | None:
    settings = get_settings()
    engine = create_engine(settings.sync_database_url)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT name, source_type, connection_config, secret_ref FROM data_sources WHERE id = :id"),
            {"id": source_id}
        ).first()
        if row:
            return dict(row._mapping)
    return None


def _is_managed_postgres_source(source_id: str) -> bool:
    try:
        ds = _get_datasource_sync(source_id)
    except Exception:
        return False
    if not ds or ds["source_type"] != "postgres":
        return False
    config = dict(ds["connection_config"] or {})
    return bool(config.get("managed"))


def _get_external_postgres_engine(source_id: str) -> Any:
    ds = _get_datasource_sync(source_id)
    if not ds:
        raise ValueError(f"Data source {source_id} not found")
    if ds["source_type"] != "postgres":
        raise ValueError(f"Data source {source_id} is not a postgres connector (got {ds['source_type']})")

    config = dict(ds["connection_config"])
    if ds["secret_ref"]:
        settings = get_settings()
        engine = create_engine(settings.sync_database_url)
        from sqlalchemy.orm import Session
        with Session(engine) as session:
            from app.permissions.secrets import get_secret_sync
            import uuid
            password = get_secret_sync(session, uuid.UUID(ds["secret_ref"]))
            config["password"] = password

    from app.connectors.postgres import _get_engine
    return _get_engine(config, statement_timeout_seconds=get_settings().sql_query_timeout_seconds)


def _rewrite_branch_schemas(sql: str, datasets: list["Dataset"] | None) -> str:
    """Replace schema references for branched postgres datasets via the AST."""
    if not datasets:
        return sql
    import sqlglot
    import sqlglot.expressions as exp

    replacements: dict[tuple[str | None, str], str] = {}
    for ds in datasets:
        branch = (getattr(ds, "branch_name", None) or "main")
        if branch == "main" or (getattr(ds, "execution_engine", None) or "postgres") != "postgres":
            continue
        branch_schema = _branch_schema(branch)
        schema_name = getattr(ds, "schema_name", None)
        replacements[((schema_name or "").lower() or None, ds.table_name.lower())] = branch_schema
        replacements[(None, ds.table_name.lower())] = branch_schema
    if not replacements:
        return sql
    root = sqlglot.parse_one(sql, read="postgres")
    for table in list(root.find_all(exp.Table)):
        if not table.name:
            continue
        schema = str(table.db).lower() if table.db else None
        branch_schema = replacements.get((schema, table.name.lower())) or replacements.get((None, table.name.lower()))
        if branch_schema:
            table.set("db", exp.to_identifier(branch_schema, quoted=True))
    return root.sql(dialect="postgres")


def _planned_cost(conn: Any, sql: str, params: dict[str, Any] | None) -> float | None:
    row = conn.execute(text(f"EXPLAIN (FORMAT JSON) {sql}"), params or {}).scalar()
    payload = json.loads(row) if isinstance(row, str) else row
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict) and isinstance(first.get("Plan"), dict):
            return float(first["Plan"].get("Total Cost", 0.0))
    return None


def _run_postgres_sql(
    sql: str,
    params: dict[str, Any] | None,
    datasets: list["Dataset"] | None = None,
    *,
    query_id: str | None = None,
) -> dict[str, Any]:
    sql = _rewrite_branch_schemas(sql, datasets)
    external_source_ids: set[str] = set()
    has_local_dataset = False
    for d in datasets or []:
        source_id = getattr(d, "source_id", None)
        if source_id and not _is_managed_postgres_source(str(source_id)):
            external_source_ids.add(str(source_id))
        else:
            has_local_dataset = True

    if len(external_source_ids) > 1:
        raise ValueError("Cannot mix multiple external postgres data sources in a single query")
    elif len(external_source_ids) == 1:
        if has_local_dataset:
            raise ValueError("Cannot mix local and remote postgres datasets in a single query")
        source_id = list(external_source_ids)[0]
        engine = _get_external_postgres_engine(str(source_id))
    else:
        settings = get_settings()
        engine = create_engine(
            settings.readonly_sync_database_url or settings.sync_database_url,
            connect_args={
                "options": (
                    "-c default_transaction_read_only=on "
                    f"-c statement_timeout={settings.sql_query_timeout_seconds * 1000}"
                )
            },
        )

    settings = get_settings()
    final_sql = _enforce_limit(sql, settings.sql_row_limit)
    with engine.connect() as conn:
        cancel_handle = None
        try:
            if query_id:
                pid = conn.execute(text("SELECT pg_backend_pid()")).scalar()

                def _cancel() -> None:
                    with engine.connect() as cancel_conn:
                        cancel_conn.execute(text("SELECT pg_cancel_backend(:pid)"), {"pid": pid})

                cancel_handle = query_registry.attach(query_id, _cancel)
                if query_registry.is_cancelled(query_id):
                    raise TimeoutError("query cancelled")
            if settings.sql_max_planned_cost and settings.sql_max_planned_cost > 0:
                cost = _planned_cost(conn, final_sql, params)
                if cost is not None and cost > settings.sql_max_planned_cost:
                    raise ValueError(
                        f"query plan cost {cost:.2f} exceeds limit {settings.sql_max_planned_cost:.2f}"
                    )
            result = conn.execute(text(final_sql), params or {})
            columns = list(result.keys())
            rows = [dict(r._mapping) for r in result]
        finally:
            if cancel_handle is not None:
                cancel_handle.close()
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


def _branch_schema(branch_name: str) -> str:
    """Map a branch name to its isolated postgres schema."""
    return f"mf_branch_{branch_name.lower().replace('-', '_')}"


def pick_engine(datasets: list["Dataset"] | None) -> str:
    """Decide which engine to dispatch to."""
    if not datasets:
        return "postgres"
    engines = {(getattr(d, "execution_engine", None) or "postgres") for d in datasets}
    if "spark" in engines:
        return "spark"
    if "duckdb" in engines and len(engines) > 1:
        raise ValueError("Cannot mix postgres and duckdb datasets in a single query")
    if "duckdb" in engines:
        return "duckdb"
    return "postgres"


def run_sql(
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    datasets: list["Dataset"] | None = None,
    query_id: str | None = None,
    storage_overrides: dict[Any, str] | None = None,
) -> dict[str, Any]:
    validate_sql(sql)
    engine = pick_engine(datasets)

    if engine == "postgres":
        return _run_postgres_sql(sql, params, datasets, query_id=query_id)
    if engine == "duckdb":
        from app.execution.duckdb_runner import run_duckdb_sql
        return run_duckdb_sql(sql, datasets or [], params, query_id=query_id, storage_overrides=storage_overrides)
    if engine == "spark":
        from app.execution.spark_runner import current_spark_runner
        return current_spark_runner().submit_sql(sql, datasets or [], {})
    raise ValueError(f"unknown engine: {engine}")
