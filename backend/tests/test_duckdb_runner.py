"""DuckDB runner: writes a tiny Parquet to a local temp dir and runs SELECT
against it through the actual run_duckdb_sql path. Skipped if duckdb or
pyarrow is unavailable.
"""
import os
import tempfile
import pytest

pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")

import pandas as pd
import pyarrow.parquet as pq
import pyarrow as pa

from app.execution.duckdb_runner import run_duckdb_sql
from app.execution.sql_validator import SqlValidationError


class _DS:
    def __init__(self, table_name: str, storage_uri: str):
        self.execution_engine = "duckdb"
        self.table_name = table_name
        self.storage_uri = storage_uri


@pytest.fixture
def tiny_parquet(tmp_path):
    path = tmp_path / "rows.parquet"
    df = pd.DataFrame({"id": [1, 2, 3], "status": ["paid", "pending", "paid"]})
    pq.write_table(pa.Table.from_pandas(df), path)
    return str(path)


def test_count_and_group_by(tiny_parquet, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    from app.config import get_settings
    get_settings.cache_clear()  # type: ignore[attr-defined]
    ds = _DS("rows", tiny_parquet)
    result = run_duckdb_sql("SELECT COUNT(*) AS n FROM rows", [ds])
    assert result["row_count"] == 1
    assert result["rows"][0]["n"] == 3


def test_unsafe_table_name_rejected(tiny_parquet):
    bad = _DS("rows; DROP TABLE x", tiny_parquet)
    with pytest.raises(Exception):
        run_duckdb_sql("SELECT 1", [bad])
