import uuid
import pytest
from unittest.mock import MagicMock
from app.execution.sql_runner import run_sql


class FakeDataset:
    def __init__(self, id, table_name, source_id=None, execution_engine="postgres"):
        self.id = id
        self.table_name = table_name
        self.source_id = source_id
        self.execution_engine = execution_engine
        self.schema_name = "public"


def test_mixed_external_sources_raises_error():
    ds1 = FakeDataset(uuid.uuid4(), "table1", source_id=uuid.uuid4())
    ds2 = FakeDataset(uuid.uuid4(), "table2", source_id=uuid.uuid4())

    with pytest.raises(ValueError) as excinfo:
        run_sql("SELECT * FROM table1 JOIN table2", datasets=[ds1, ds2])
    assert "Cannot mix multiple external postgres data sources" in str(excinfo.value)


def test_mixed_local_and_remote_raises_error():
    ds1 = FakeDataset(uuid.uuid4(), "table1", source_id=None)
    ds2 = FakeDataset(uuid.uuid4(), "table2", source_id=uuid.uuid4())

    with pytest.raises(ValueError) as excinfo:
        run_sql("SELECT * FROM table1 JOIN table2", datasets=[ds1, ds2])
    assert "Cannot mix local and remote postgres datasets" in str(excinfo.value)


def test_routing_to_single_external_source(monkeypatch):
    source_id = uuid.uuid4()
    ds = FakeDataset(uuid.uuid4(), "table1", source_id=source_id)

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    # Mock execute result
    mock_result = MagicMock()
    mock_result.keys.return_value = ["id", "val"]
    mock_result.__iter__.return_value = []
    mock_conn.execute.return_value = mock_result

    # Mock _get_external_postgres_engine in sql_runner module
    import app.execution.sql_runner
    monkeypatch.setattr(
        app.execution.sql_runner,
        "_get_external_postgres_engine",
        lambda sid: mock_engine
    )

    res = run_sql("SELECT * FROM table1", datasets=[ds])
    assert res["columns"] == ["id", "val"]
    assert mock_conn.execute.called


def test_managed_postgres_source_routes_to_local_engine(monkeypatch):
    source_id = uuid.uuid4()
    ds = FakeDataset(uuid.uuid4(), "table1", source_id=source_id)

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_result = MagicMock()
    mock_result.keys.return_value = ["id"]
    mock_result.__iter__.return_value = []
    mock_conn.execute.return_value = mock_result

    import app.execution.sql_runner

    monkeypatch.setattr(app.execution.sql_runner, "_is_managed_postgres_source", lambda sid: sid == str(source_id))
    monkeypatch.setattr(app.execution.sql_runner, "create_engine", lambda *args, **kwargs: mock_engine)
    monkeypatch.setattr(
        app.execution.sql_runner,
        "_get_external_postgres_engine",
        lambda sid: (_ for _ in ()).throw(AssertionError("managed source should not use external engine")),
    )

    res = run_sql("SELECT * FROM table1", datasets=[ds])
    assert res["columns"] == ["id"]
    assert mock_conn.execute.called


def test_managed_and_external_postgres_mix_raises(monkeypatch):
    managed = uuid.uuid4()
    external = uuid.uuid4()
    ds1 = FakeDataset(uuid.uuid4(), "table1", source_id=managed)
    ds2 = FakeDataset(uuid.uuid4(), "table2", source_id=external)

    import app.execution.sql_runner

    monkeypatch.setattr(app.execution.sql_runner, "_is_managed_postgres_source", lambda sid: sid == str(managed))
    with pytest.raises(ValueError) as excinfo:
        run_sql("SELECT * FROM table1 JOIN table2 ON true", datasets=[ds1, ds2])
    assert "Cannot mix local and remote postgres datasets" in str(excinfo.value)
