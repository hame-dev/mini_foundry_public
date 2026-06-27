import pytest

from app.execution.sql_validator import SqlValidationError
from app.governed_query.rewrite import TableSpec, compile_governed_source_sql


def _spec(masks=None, columns=None, rls=None):
    return {
        "customers": TableSpec(
            table_name="customers",
            schema_name="public",
            real_table="customers",
            columns=columns if columns is not None else ["id", "name", "ssn", "region"],
            masks=masks or {},
            rls=rls,
        )
    }


def test_hidden_column_dropped_from_projection():
    out = compile_governed_source_sql("SELECT * FROM customers", _spec(masks={"ssn": "hidden"}))
    # source table wrapped in a subquery, ssn not projected
    assert "FROM (SELECT" in out
    assert '"id"' in out and '"name"' in out and '"region"' in out
    assert '"ssn"' not in out


def test_null_hash_partial_expressions():
    out = compile_governed_source_sql(
        "SELECT * FROM customers",
        _spec(masks={"name": "null", "ssn": "hash", "region": "partial"}),
    )
    assert 'NULL AS "name"' in out
    assert 'md5(CAST("ssn" AS VARCHAR)) AS "ssn"' in out.replace("MD5", "md5")
    assert "CASE WHEN LENGTH" in out.upper() or "case when length" in out.lower()
    assert '"id"' in out  # passthrough column retained


def test_rls_condition_preserved_in_subquery():
    out = compile_governed_source_sql(
        "SELECT * FROM customers", _spec(masks={"ssn": "hidden"}, rls="region = 'EMEA'")
    )
    assert "WHERE" in out.upper()
    assert "EMEA" in out


def test_parse_failure_fails_closed():
    with pytest.raises(SqlValidationError):
        compile_governed_source_sql("SELECT FROM FROM ((", _spec(masks={"ssn": "hidden"}))


def test_unknown_columns_fall_back_to_star():
    # No known columns -> projection is * (post-query masking handles redaction).
    out = compile_governed_source_sql(
        "SELECT * FROM customers", _spec(masks={"ssn": "hidden"}, columns=[])
    )
    assert "SELECT * FROM" in out.replace("\n", " ")


def test_table_not_in_specs_untouched():
    out = compile_governed_source_sql("SELECT * FROM other_table", _spec(masks={"ssn": "hidden"}))
    assert "other_table" in out
    assert "(SELECT" not in out


def test_no_specs_returns_original():
    sql = "SELECT 1"
    assert compile_governed_source_sql(sql, {}) == sql
