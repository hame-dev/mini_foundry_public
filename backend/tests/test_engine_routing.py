import pytest
from app.execution.sql_runner import pick_engine


class _DS:
    def __init__(self, engine):
        self.execution_engine = engine


def test_pick_engine_no_datasets_defaults_postgres():
    assert pick_engine(None) == "postgres"
    assert pick_engine([]) == "postgres"


def test_pick_engine_all_duckdb():
    assert pick_engine([_DS("duckdb"), _DS("duckdb")]) == "duckdb"


def test_pick_engine_mixed_postgres_duckdb_raises():
    with pytest.raises(ValueError):
        pick_engine([_DS("postgres"), _DS("duckdb")])


def test_pick_engine_spark_wins():
    assert pick_engine([_DS("spark"), _DS("postgres")]) == "spark"
    assert pick_engine([_DS("spark"), _DS("duckdb")]) == "spark"


def test_pick_engine_postgres_only():
    assert pick_engine([_DS("postgres"), _DS("postgres")]) == "postgres"


def test_spark_runner_not_configured_raises():
    from app.execution.spark_runner import current_spark_runner
    with pytest.raises(NotImplementedError):
        current_spark_runner().submit_sql("SELECT 1", [], {})


def test_trino_runner_python_methods_fail_explicitly():
    from app.execution.spark_runner import TrinoSparkRunner

    runner = TrinoSparkRunner(host="trino.local")
    with pytest.raises(NotImplementedError, match="Spark Python jobs are not wired"):
        runner.submit_python("print('x')", [], {})
    assert runner.get_job_status("job") == "not_supported"
    assert runner.get_job_result("job") == {}
