from __future__ import annotations

from dataclasses import dataclass

import sqlglot
import sqlglot.expressions as exp

from app.execution.sql_validator import SqlValidationError


@dataclass(frozen=True)
class TableReference:
    table: str
    schema: str | None = None

    @property
    def table_key(self) -> str:
        return self.table.lower()

    @property
    def qualified_key(self) -> str:
        return table_key(self.schema, self.table)


def table_key(schema: str | None, table: str) -> str:
    schema_part = (schema or "").lower()
    table_part = table.lower()
    return f"{schema_part}.{table_part}" if schema_part else table_part


def parse_select(sql: str, dialect: str = "postgres") -> exp.Expression:
    try:
        statements = sqlglot.parse(sql.strip().rstrip(";"), read=dialect)
    except sqlglot.errors.ParseError as e:
        raise SqlValidationError(f"parse error: {e}") from e
    parsed = [s for s in statements if s is not None]
    if len(parsed) != 1:
        raise SqlValidationError("only a single statement is allowed")
    return parsed[0]


def referenced_table_refs(sql: str, dialect: str = "postgres") -> list[TableReference]:
    """Return base table references, excluding CTE aliases and table functions."""

    root = parse_select(sql, dialect=dialect)
    cte_names = {str(cte.alias).lower() for cte in root.find_all(exp.CTE) if cte.alias}
    refs: list[TableReference] = []
    seen: set[str] = set()
    for table in root.find_all(exp.Table):
        name = table.name
        if not name:
            continue
        schema = str(table.db) if table.db else None
        if not schema and name.lower() in cte_names:
            continue
        ref = TableReference(table=name, schema=schema)
        if ref.qualified_key in seen:
            continue
        seen.add(ref.qualified_key)
        refs.append(ref)
    return refs


def referenced_table_names(sql: str, dialect: str = "postgres") -> list[str]:
    names: list[str] = []
    for ref in referenced_table_refs(sql, dialect=dialect):
        if ref.table not in names:
            names.append(ref.table)
    return names


def enforce_outer_limit(sql: str, row_limit: int, dialect: str = "postgres") -> str:
    """Apply a hard cap to the outer SELECT AST.

    This deliberately ignores LIMIT occurrences in subqueries, identifiers, and
    literals. If an outer literal LIMIT is lower than the platform cap we keep it;
    any missing, non-literal, or higher outer limit is replaced with row_limit.
    """

    root = parse_select(sql, dialect=dialect)
    limit = root.args.get("limit")
    keep_existing = False
    if isinstance(limit, exp.Limit):
        literal = limit.expression
        if isinstance(literal, exp.Literal) and not literal.is_string:
            try:
                keep_existing = int(literal.this) <= row_limit
            except (TypeError, ValueError):
                keep_existing = False
    if not keep_existing:
        root.set("limit", exp.Limit(expression=exp.Literal.number(max(1, int(row_limit)))))
    return root.sql(dialect=dialect)
