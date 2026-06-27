import pytest
from app.execution.sql_validator import validate_sql, SqlValidationError


def test_select_passes():
    validate_sql("SELECT 1")
    validate_sql("SELECT id, name FROM customers WHERE id = 1 LIMIT 10")


def test_cte_select_passes():
    validate_sql("WITH t AS (SELECT 1 AS x) SELECT * FROM t")


def test_union_passes():
    validate_sql("SELECT 1 UNION SELECT 2")


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE customers",
        "DELETE FROM orders",
        "UPDATE orders SET status = 'x'",
        "INSERT INTO orders (id) VALUES (1)",
        "ALTER TABLE orders ADD COLUMN x INT",
        "TRUNCATE orders",
        "CREATE TABLE foo (id INT)",
    ],
)
def test_forbidden_statements_rejected(sql):
    with pytest.raises(SqlValidationError):
        validate_sql(sql)


def test_multi_statement_rejected():
    with pytest.raises(SqlValidationError):
        validate_sql("SELECT 1; SELECT 2;")


def test_empty_rejected():
    with pytest.raises(SqlValidationError):
        validate_sql("   ")


def test_unparseable_rejected():
    with pytest.raises(SqlValidationError):
        validate_sql("SELECT FROM WHERE")
