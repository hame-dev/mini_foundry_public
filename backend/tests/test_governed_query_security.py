import pytest

from app.execution.sql_validator import SqlValidationError
from app.governed_query.rewrite import TableSpec, compile_governed_source_sql
from app.governed_query.service import _is_allowlisted_constant_query
from app.execution.sql_validator import validate_sql


def test_cte_alias_shadowing_is_not_rewritten():
    sql = 'WITH customers AS (SELECT 1 AS id) SELECT * FROM customers'
    out = compile_governed_source_sql(
        sql,
        {
            "customers": TableSpec(
                table_name="customers",
                schema_name="public",
                real_table="customers",
                columns=["id"],
                masks={},
            )
        },
    )
    assert 'FROM "public"."customers"' not in out
    assert "WITH customers AS" in out


def test_constant_query_allowlist_accepts_literals_only():
    assert _is_allowlisted_constant_query(validate_sql("SELECT 1, 'x' AS label"))
    assert not _is_allowlisted_constant_query(validate_sql("SELECT current_database()"))


def test_constant_query_allowlist_rejects_non_select():
    with pytest.raises(SqlValidationError):
        validate_sql("SET statement_timeout = 1")
