"""SQL validator: enforce SELECT-only, single-statement, no DDL/DML.

We parse with sqlglot (postgres dialect by default) and walk the AST to
reject any forbidden node type. Word-level blocklisting alone is unsafe
(it would match column names like `user_updated_at`), so we rely on the
parser.
"""
import sqlglot
import sqlglot.expressions as exp
import re


def _expression_type(name: str) -> type[exp.Expression] | None:
    node_type = getattr(exp, name, None)
    if isinstance(node_type, type):
        return node_type
    return None


FORBIDDEN_NODE_TYPES = tuple(
    node_type
    for name in (
        "Insert",
        "Update",
        "Delete",
        "Drop",
        "Alter",
        "AlterTable",
        "Create",
        "Truncate",
        "TruncateTable",
        "Merge",
        "Command",
    )
    if (node_type := _expression_type(name)) is not None
)


class SqlValidationError(ValueError):
    pass


UNSAFE_KEYWORDS = re.compile(r"^\s*(COPY|CALL|DO|SET|RESET|VACUUM|ANALYZE|EXPLAIN|GRANT|REVOKE|LISTEN|NOTIFY)\b", re.IGNORECASE)
UNSAFE_FUNCTIONS = {
    "pg_read_file",
    "pg_ls_dir",
    "dblink",
    "lo_import",
    "lo_export",
    "http_get",
    "http_post",
    "read_parquet",
    "read_csv",
    "read_csv_auto",
    "read_json",
    "read_json_auto",
    "read_ndjson",
    "read_blob",
    "parquet_scan",
    "csv_scan",
    "json_scan",
    "httpfs",
}


def validate_sql(sql: str, dialect: str = "postgres") -> exp.Expression:
    sql = sql.strip().rstrip(";")
    if not sql:
        raise SqlValidationError("empty SQL")
    if UNSAFE_KEYWORDS.search(sql):
        raise SqlValidationError("unsafe SQL command is not allowed")

    try:
        statements = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.ParseError as e:
        raise SqlValidationError(f"parse error: {e}") from e

    parsed = [s for s in statements if s is not None]
    if len(parsed) != 1:
        raise SqlValidationError("only a single statement is allowed")

    root = parsed[0]
    if not isinstance(root, (exp.Select, exp.Union, exp.With, exp.Subquery)):
        raise SqlValidationError(f"only SELECT statements are allowed (got {type(root).__name__})")

    for node in root.walk():
        n = node[0] if isinstance(node, tuple) else node
        if isinstance(n, FORBIDDEN_NODE_TYPES):
            raise SqlValidationError(f"forbidden SQL construct: {type(n).__name__}")
        if isinstance(n, exp.Anonymous) and str(n.name).lower() in UNSAFE_FUNCTIONS:
            raise SqlValidationError(f"unsafe SQL function is not allowed: {n.name}")
        if isinstance(n, exp.Table) and isinstance(n.this, exp.Anonymous):
            fn_name = str(n.this.name).lower()
            if fn_name in UNSAFE_FUNCTIONS:
                raise SqlValidationError(f"unsafe SQL table function is not allowed: {fn_name}")

    return root
