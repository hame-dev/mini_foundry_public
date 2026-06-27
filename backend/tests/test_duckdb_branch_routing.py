import uuid

import pytest

from app.execution.duckdb_runner import _reject_external_postgres_on_duckdb_path, run_duckdb_sql


class FakeDataset:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid.uuid4())
        self.table_name = kwargs.get("table_name", "rows")
        self.schema_name = kwargs.get("schema_name", "public")
        self.execution_engine = kwargs.get("execution_engine", "postgres")
        self.source_id = kwargs.get("source_id")
        self.branch_name = kwargs.get("branch_name", "main")
        self.storage_uri = kwargs.get("storage_uri")


def test_duckdb_path_rejects_external_postgres(monkeypatch):
    ds = FakeDataset(source_id=uuid.uuid4())

    monkeypatch.setattr(
        "app.execution.sql_runner._is_managed_postgres_source",
        lambda _sid: False,
    )

    with pytest.raises(ValueError, match="external postgres"):
        run_duckdb_sql("SELECT 1", [ds])


def test_reject_external_helper(monkeypatch):
    ds = FakeDataset(source_id=uuid.uuid4())
    monkeypatch.setattr(
        "app.execution.sql_runner._is_managed_postgres_source",
        lambda _sid: False,
    )
    with pytest.raises(ValueError, match="external postgres"):
        _reject_external_postgres_on_duckdb_path([ds])
