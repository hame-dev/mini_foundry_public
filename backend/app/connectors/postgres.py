from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.connectors.base import Connector

_engine_cache: dict[str, Engine] = {}


def _build_url(cfg: dict[str, Any]) -> str:
    for key in ("username", "host", "database"):
        if cfg.get(key) in (None, ""):
            raise ValueError(f"postgres connector missing required config key: {key}")
    user = quote_plus(cfg["username"])
    pw = quote_plus(cfg.get("password", ""))
    host = cfg["host"]
    port = cfg.get("port", 5432)
    db = cfg["database"]
    sslmode = cfg.get("ssl_mode", "prefer")
    return f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{db}?sslmode={sslmode}"


def _get_engine(cfg: dict[str, Any], statement_timeout_seconds: int | None = None) -> Engine:
    url = _build_url(cfg)
    timeout_ms = int((statement_timeout_seconds or 0) * 1000)
    cache_key = f"{url}|timeout={timeout_ms}"
    options = "-c default_transaction_read_only=on"
    if timeout_ms > 0:
        options += f" -c statement_timeout={timeout_ms}"
    if cache_key not in _engine_cache:
        _engine_cache[cache_key] = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=2,
            connect_args={"options": options},
        )
    return _engine_cache[cache_key]


class PostgresConnector(Connector):
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.allowed_schemas: list[str] = config.get("schemas") or ["public"]
        self.allowed_tables: list[str] | None = config.get("allowed_tables")

    @property
    def _engine(self) -> Engine:
        return _get_engine(self.config)

    def test_connection(self) -> dict[str, Any]:
        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}

    def discover_schema(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        inspector = inspect(self._engine)
        for schema in self.allowed_schemas:
            for table in inspector.get_table_names(schema=schema):
                if self.allowed_tables and table not in self.allowed_tables:
                    continue
                cols = []
                for c in inspector.get_columns(table, schema=schema):
                    cols.append({"name": c["name"], "type": str(c["type"])})
                out.append({"schema": schema, "table": table, "columns": cols})
        return out

    def preview(self, schema: str, table: str, limit: int = 100) -> list[dict[str, Any]]:
        if schema not in self.allowed_schemas:
            raise PermissionError(f"schema not allowed: {schema}")
        if self.allowed_tables and table not in self.allowed_tables:
            raise PermissionError(f"table not allowed: {table}")
        # identifiers validated via allowlist above
        with self._engine.connect() as conn:
            result = conn.execute(text(f'SELECT * FROM "{schema}"."{table}" LIMIT :n'), {"n": limit})
            return [dict(r._mapping) for r in result]

    def query(self, sql: str, params: dict | None = None) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            return [dict(r._mapping) for r in result]
