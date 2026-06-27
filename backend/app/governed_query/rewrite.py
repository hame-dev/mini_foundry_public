"""Compile row policies + column masks into the SQL source projection.

Instead of masking result rows after the engine runs, we rewrite each governed
dataset table into a subquery that (a) applies the row-policy WHERE on the raw
table and (b) projects masked/dropped columns. The engine therefore never reads
hidden columns and cannot filter/group on them, and masked values are redacted
before execution. Both supported engines (postgres, duckdb) accept the masking
expressions below.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
import sqlglot.expressions as exp

from app.execution.sql_validator import SqlValidationError
from app.execution.sql_utils import table_key


@dataclass
class TableSpec:
    table_name: str            # lowercase bare table name (match key)
    schema_name: str
    real_table: str
    columns: list[str] = field(default_factory=list)   # known column names ([] = unknown)
    masks: dict[str, str] = field(default_factory=dict)  # col -> hidden|null|hash|partial
    rls: str | None = None     # SQL WHERE condition, or None


def _qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _mask_expr(col: str, mask: str) -> str | None:
    """Return the SELECT expression for a column, or None if hidden (omit)."""
    q = _qident(col)
    if mask == "hidden":
        return None
    if mask == "null":
        return f"NULL AS {q}"
    if mask == "hash":
        return f"md5(CAST({q} AS VARCHAR)) AS {q}"
    if mask == "partial":
        v = f"CAST({q} AS VARCHAR)"
        return (
            f"CASE WHEN LENGTH({v}) > 4 THEN "
            f"SUBSTR({v}, 1, 2) || '***' || SUBSTR({v}, LENGTH({v}) - 1) "
            f"ELSE {v} END AS {q}"
        )
    return q  # "none" / unknown → passthrough


def _projection(spec: TableSpec) -> str:
    """Build the SELECT projection list for a masked source subquery.

    When columns are unknown we cannot drop hidden columns safely, so we fall
    back to `*` and rely on post-query masking as defense-in-depth.
    """
    if not spec.columns:
        return "*"
    parts: list[str] = []
    for col in spec.columns:
        expr = _mask_expr(col, spec.masks.get(col, "none"))
        if expr is not None:
            parts.append(expr)
    if not parts:
        # Every column hidden — emit a single placeholder so the SQL is valid.
        return "NULL AS \"_redacted\""
    return ", ".join(parts)


def compile_governed_source_sql(
    sql: str, specs: dict[str, TableSpec], dialect: str = "postgres"
) -> str:
    """Rewrite governed dataset tables into masked + row-filtered subqueries.

    `specs` maps lowercase table name or schema.table -> TableSpec. Tables not
    in `specs` are left untouched. Fails closed (raises SqlValidationError) if
    the SQL cannot be parsed, so an unparseable query is never run unmasked.
    """
    if not sql.strip() or not specs:
        return sql
    # duckdb shares postgres-style identifier/function syntax for our masks.
    read_dialect = "postgres" if dialect not in ("postgres", "duckdb") else dialect
    try:
        statements = sqlglot.parse(sql, read=read_dialect)
        parsed = [s for s in statements if s is not None]
        if not parsed:
            return sql
        root = parsed[0]
    except Exception as e:  # noqa: BLE001
        raise SqlValidationError(f"unable to apply governed masking: {e}") from e

    cte_names = {str(cte.alias).lower() for cte in root.find_all(exp.CTE) if cte.alias}
    for table_node in list(root.find_all(exp.Table)):
        schema = str(table_node.db) if table_node.db else None
        if not schema and table_node.name.lower() in cte_names:
            continue
        spec = specs.get(table_key(schema, table_node.name)) or specs.get(table_node.name.lower())
        if spec is None:
            continue
        alias = table_node.alias_or_name
        proj = _projection(spec)
        if dialect == "duckdb":
            source = _qident(spec.real_table)
        else:
            source = f"{_qident(spec.schema_name)}.{_qident(spec.real_table)}"
        where = f" WHERE {spec.rls}" if spec.rls else ""
        subquery_sql = f"(SELECT {proj} FROM {source}{where}) AS {_qident(alias)}"
        new_node = sqlglot.parse_one(subquery_sql, read=read_dialect)
        table_node.replace(new_node)

    return root.sql(dialect=read_dialect)
