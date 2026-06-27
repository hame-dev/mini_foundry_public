"""Spark / Trino execution interface.

When TRINO_HOST is set in environment, the TrinoSparkRunner is active and
routes SQL through a Trino coordinator (which can front Spark, Hive, Iceberg
or any Trino catalog). Without TRINO_HOST, falls back to DuckDB via the
NotConfiguredSparkRunner so no code path breaks.

To wire in a real cluster:
  export TRINO_HOST=trino.internal
  export TRINO_PORT=8080          (optional, default 8080)
  export TRINO_USER=mini-foundry  (optional, default mini-foundry)
  export TRINO_CATALOG=hive       (optional, default hive)
  export TRINO_SCHEMA=default     (optional, default default)
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.data.models import Dataset


class SparkRunner(ABC):
    @abstractmethod
    def submit_sql(self, sql: str, datasets: list["Dataset"], user_context: dict) -> dict[str, Any]: ...

    @abstractmethod
    def submit_python(self, code: str, datasets: list["Dataset"], user_context: dict) -> str: ...

    @abstractmethod
    def get_job_status(self, job_id: str) -> str: ...

    @abstractmethod
    def get_job_result(self, job_id: str) -> dict[str, Any]: ...


class NotConfiguredSparkRunner(SparkRunner):
    """Falls back to DuckDB when Trino is not configured."""

    def submit_sql(self, sql: str, datasets: list["Dataset"], user_context: dict) -> dict[str, Any]:
        from app.execution.duckdb_runner import run_duckdb_sql
        duckdb_datasets = [d for d in datasets if d.storage_uri]
        if not duckdb_datasets:
            raise NotImplementedError(
                "Spark/Trino is not configured (set TRINO_HOST) and no DuckDB datasets "
                "are available for fallback."
            )
        return run_duckdb_sql(sql, duckdb_datasets, {})

    def submit_python(self, code: str, datasets: list["Dataset"], user_context: dict) -> str:
        raise NotImplementedError("Spark/Trino not configured. Set TRINO_HOST to enable.")

    def get_job_status(self, job_id: str) -> str:
        return "not_configured"

    def get_job_result(self, job_id: str) -> dict[str, Any]:
        return {}


def _enforce_limit(sql: str, row_limit: int) -> str:
    import re
    if re.search(r"\blimit\b", sql, re.IGNORECASE):
        return sql
    return f"{sql.rstrip(';')} LIMIT {row_limit}"


class TrinoSparkRunner(SparkRunner):
    """Routes SQL through a Trino coordinator.

    Synchronous: Trino queries return inline results (no async job lifecycle
    needed for SQL). For long-running Python jobs we enqueue a Celery task
    and return a synthetic job_id.
    """

    def __init__(
        self,
        host: str,
        port: int = 8080,
        user: str = "mini-foundry",
        catalog: str = "hive",
        schema: str = "default",
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.catalog = catalog
        self.schema = schema

    def _connect(self):
        try:
            import trino
        except ImportError as exc:
            raise RuntimeError(
                "trino package not installed. Add 'trino' to requirements.txt."
            ) from exc
        return trino.dbapi.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            catalog=self.catalog,
            schema=self.schema,
        )

    def submit_sql(self, sql: str, datasets: list["Dataset"], user_context: dict) -> dict[str, Any]:
        from app.config import get_settings
        settings = get_settings()
        conn = self._connect()
        cur = conn.cursor()
        final_sql = _enforce_limit(sql, settings.sql_row_limit)
        cur.execute(final_sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {"columns": columns, "rows": rows, "row_count": len(rows)}

    def submit_python(self, code: str, datasets: list["Dataset"], user_context: dict) -> str:
        raise NotImplementedError(
            "Spark Python jobs are not wired yet. SQL can route through Trino; "
            "use notebook sandbox jobs for Python execution."
        )

    def get_job_status(self, job_id: str) -> str:
        return "not_supported"

    def get_job_result(self, job_id: str) -> dict[str, Any]:
        return {}


class SparkConnectRunner(SparkRunner):
    """Routes SQL through a Spark Connect server using pyspark."""

    def __init__(self, remote_url: str) -> None:
        self.remote_url = remote_url
        self._spark = None

    def _get_spark(self):
        if self._spark is None:
            try:
                from pyspark.sql import SparkSession
            except ImportError as exc:
                raise RuntimeError(
                    "pyspark package not installed. Add 'pyspark' to requirements.txt."
                ) from exc
            self._spark = SparkSession.builder.remote(self.remote_url).getOrCreate()
        return self._spark

    def submit_sql(self, sql: str, datasets: list["Dataset"], user_context: dict) -> dict[str, Any]:
        spark = self._get_spark()
        from app.config import get_settings
        from urllib.parse import urlparse
        settings = get_settings()

        for ds in datasets:
            if ds.storage_uri:
                df = spark.read.parquet(ds.storage_uri)
                df.createOrReplaceTempView(ds.table_name)
            elif (getattr(ds, "execution_engine", None) or "postgres") == "postgres":
                parsed = urlparse(settings.sync_database_url)
                user = parsed.username or "mini"
                password = parsed.password or "mini"
                jdbc_url = f"jdbc:postgresql://{parsed.hostname}:{parsed.port or 5432}{parsed.path}"
                df = spark.read.format("jdbc").options(
                    url=jdbc_url,
                    dbtable=f'"{ds.schema_name}"."{ds.table_name}"',
                    user=user,
                    password=password,
                    driver="org.postgresql.Driver"
                ).load()
                df.createOrReplaceTempView(ds.table_name)

        final_sql = _enforce_limit(sql, settings.sql_row_limit)
        res_df = spark.sql(final_sql)
        columns = list(res_df.columns)
        rows = [row.asDict() for row in res_df.collect()]
        return {"columns": columns, "rows": rows, "row_count": len(rows)}

    def submit_python(self, code: str, datasets: list["Dataset"], user_context: dict) -> str:
        raise NotImplementedError("Submit python not supported on Spark Connect yet.")

    def get_job_status(self, job_id: str) -> str:
        return "not_supported"

    def get_job_result(self, job_id: str) -> dict[str, Any]:
        return {}


def _build_default_runner() -> SparkRunner:
    from app.config import get_settings
    try:
        settings = get_settings()
        runner_type = os.environ.get("SPARK_RUNNER_TYPE", settings.spark_runner_type)
        if runner_type == "spark":
            url = os.environ.get("SPARK_CONNECT_URL", settings.spark_connect_url)
            if url:
                return SparkConnectRunner(remote_url=url)
        else:
            host = os.environ.get("TRINO_HOST", settings.trino_host)
            if host:
                return TrinoSparkRunner(
                    host=host,
                    port=int(os.environ.get("TRINO_PORT", str(settings.trino_port))),
                    user=os.environ.get("TRINO_USER", settings.trino_user),
                    catalog=os.environ.get("TRINO_CATALOG", settings.trino_catalog),
                    schema=os.environ.get("TRINO_SCHEMA", settings.trino_schema),
                )
    except Exception:
        pass
    return NotConfiguredSparkRunner()


_runner: SparkRunner = _build_default_runner()


def register_spark_runner(runner: SparkRunner) -> None:
    global _runner
    _runner = runner


def current_spark_runner() -> SparkRunner:
    return _runner

