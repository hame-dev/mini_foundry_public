import os
import pytest
from unittest.mock import MagicMock, patch
from app.execution.spark_runner import (
    TrinoSparkRunner,
    SparkConnectRunner,
    _build_default_runner,
    _enforce_limit,
)
from app.data.models import Dataset


def test_enforce_limit():
    assert _enforce_limit("SELECT * FROM t", 10) == "SELECT * FROM t LIMIT 10"
    assert _enforce_limit("SELECT * FROM t LIMIT 5", 10) == "SELECT * FROM t LIMIT 5"
    assert _enforce_limit("SELECT * FROM t;", 10) == "SELECT * FROM t LIMIT 10"


def test_trino_runner_submit_sql():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.description = [("id", None, None, None, None, None, None), ("name", None, None, None, None, None, None)]
    mock_cursor.fetchall.return_value = [(1, "Alice"), (2, "Bob")]
    mock_conn.cursor.return_value = mock_cursor

    runner = TrinoSparkRunner(host="localhost")
    with patch.object(runner, "_connect", return_value=mock_conn):
        res = runner.submit_sql("SELECT * FROM users", [], {})
        
        assert res["row_count"] == 2
        assert res["columns"] == ["id", "name"]
        assert res["rows"] == [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        mock_cursor.execute.assert_called_once_with("SELECT * FROM users LIMIT 1000")


def test_spark_connect_runner_submit_sql():
    mock_spark = MagicMock()
    mock_df = MagicMock()
    mock_row_1 = MagicMock()
    mock_row_1.asDict.return_value = {"id": 1, "val": "foo"}
    mock_df.columns = ["id", "val"]
    mock_df.collect.return_value = [mock_row_1]
    mock_spark.sql.return_value = mock_df

    mock_read = MagicMock()
    mock_read.parquet.return_value = MagicMock()
    mock_read.format.return_value.options.return_value.load.return_value = MagicMock()
    mock_spark.read = mock_read

    runner = SparkConnectRunner(remote_url="sc://localhost:15002")
    with patch.object(runner, "_get_spark", return_value=mock_spark):
        ds_parquet = Dataset(
            table_name="t_parquet",
            storage_uri="s3://bucket/t.parquet",
            execution_engine="duckdb",
        )
        ds_postgres = Dataset(
            schema_name="public",
            table_name="t_postgres",
            execution_engine="postgres",
        )

        res = runner.submit_sql(
            "SELECT * FROM t_parquet JOIN t_postgres USING (id)",
            [ds_parquet, ds_postgres],
            {},
        )

        assert res["row_count"] == 1
        assert res["columns"] == ["id", "val"]
        assert res["rows"] == [{"id": 1, "val": "foo"}]

        # Check registrations
        mock_read.parquet.assert_called_once_with("s3://bucket/t.parquet")
        mock_read.format.assert_called_once_with("jdbc")


def test_build_default_runner_selection():
    # 1. Trino selected
    with patch.dict(os.environ, {"SPARK_RUNNER_TYPE": "trino", "TRINO_HOST": "trino-host"}):
        runner = _build_default_runner()
        assert isinstance(runner, TrinoSparkRunner)
        assert runner.host == "trino-host"

    # 2. Spark selected
    with patch.dict(os.environ, {"SPARK_RUNNER_TYPE": "spark", "SPARK_CONNECT_URL": "sc://spark-host:15002"}):
        runner = _build_default_runner()
        assert isinstance(runner, SparkConnectRunner)
        assert runner.remote_url == "sc://spark-host:15002"
