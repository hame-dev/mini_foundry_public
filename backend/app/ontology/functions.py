"""Functions on Objects — computed (derived) read-only properties.

A function is a scalar SQL *expression* over an object type's own columns
(e.g. ``quantity * unit_price``, ``first_name || ' ' || last_name``). It is
**not** free SQL: before an expression is ever spliced into a governed SELECT we
parse it with sqlglot and assert that it only references the object's declared
columns and an allowlist of safe scalar functions. Subqueries, table references,
and DDL/DML are rejected.

Mask-awareness: a function whose expression references a column the requesting
user has masked must not leak the underlying value, so at query-assembly time we
emit ``NULL AS name`` for it instead of the expression (see ``build_function_select``).
"""
from __future__ import annotations

import sqlglot
import sqlglot.expressions as exp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ontology.models import OntologyFunction
from app.util.identifiers import assert_safe_ident, quote_ident

# Safe scalar functions usable inside a computed property. Anything not listed is
# rejected — this is an allowlist on purpose (the SQL validator's blocklist guards
# raw queries; computed expressions get the stricter treatment).
FUNCTION_ALLOWLIST = {
    "upper", "lower", "concat", "coalesce", "nullif", "abs", "round", "ceil",
    "floor", "length", "char_length", "substr", "substring", "trim", "ltrim",
    "rtrim", "replace", "left", "right", "lpad", "rpad", "cast", "extract",
    "date_trunc", "date_part", "greatest", "least", "mod", "power", "sqrt",
    "to_char", "now", "current_date",
}


class BadFunctionExpression(ValueError):
    pass


def validate_function_expression(expression: str, allowed_columns: set[str]) -> set[str]:
    """Validate a computed-property expression and return the columns it references.

    Raises ``BadFunctionExpression`` if the expression parses to anything other
    than a single safe scalar expression over ``allowed_columns``.
    """
    text = (expression or "").strip()
    if not text:
        raise BadFunctionExpression("expression is empty")
    try:
        # Parse as an expression (not a statement). sqlglot returns the root node.
        root = sqlglot.parse_one(text, read="postgres")
    except sqlglot.errors.ParseError as e:
        raise BadFunctionExpression(f"parse error: {e}") from e
    if root is None:
        raise BadFunctionExpression("could not parse expression")
    # A bare SELECT / set operation / statement is not a scalar expression.
    if isinstance(root, (exp.Select, exp.Union, exp.With, exp.Subquery, exp.Command)):
        raise BadFunctionExpression("expression must be a scalar value, not a query")

    referenced: set[str] = set()
    for node in root.walk():
        n = node[0] if isinstance(node, tuple) else node
        if isinstance(n, (exp.Subquery, exp.Select)):
            raise BadFunctionExpression("subqueries are not allowed in a computed property")
        if isinstance(n, exp.Table):
            raise BadFunctionExpression("table references are not allowed in a computed property")
        if isinstance(n, exp.Star):
            raise BadFunctionExpression("'*' is not allowed in a computed property")
        if isinstance(n, exp.Column):
            if n.table:
                raise BadFunctionExpression(f"table-qualified columns are not allowed: {n.sql()}")
            col = n.name
            if col not in allowed_columns:
                raise BadFunctionExpression(f"unknown column in expression: {col!r}")
            referenced.add(col)
        # Reject any function not in the allowlist. ``exp.Func`` subclasses cover
        # both named builtins (e.g. exp.Upper) and anonymous calls (exp.Anonymous).
        if isinstance(n, exp.Func):
            fn_name = (n.sql_name() or n.name or type(n).__name__).lower()
            if isinstance(n, exp.Anonymous):
                fn_name = str(n.name).lower()
            if fn_name not in FUNCTION_ALLOWLIST:
                raise BadFunctionExpression(f"function not allowed in a computed property: {fn_name}")
    return referenced


def build_function_select(
    functions: list[dict], masked_columns: set[str]
) -> tuple[list[str], list[str]]:
    """Build the SELECT-list fragments for the given computed properties.

    Each ``functions`` entry is ``{"name", "expression", "columns": set[str]}``.
    Returns ``(select_fragments, names)``. A function whose referenced columns
    intersect ``masked_columns`` is redacted to ``NULL AS name`` so masked data
    cannot leak through a derived value.
    """
    fragments: list[str] = []
    names: list[str] = []
    for fn in functions:
        name = fn["name"]
        assert_safe_ident(name)
        names.append(name)
        cols = set(fn.get("columns") or ())
        if cols & masked_columns:
            fragments.append(f"NULL AS {quote_ident(name)}")
        else:
            fragments.append(f"({fn['expression']}) AS {quote_ident(name)}")
    return fragments, names


async def get_functions(session: AsyncSession, object_type: str) -> list[OntologyFunction]:
    result = await session.execute(
        select(OntologyFunction)
        .where(OntologyFunction.object_type == object_type)
        .order_by(OntologyFunction.name)
    )
    return list(result.scalars().all())


async def resolve_function_specs(
    session: AsyncSession, object_type: str, allowed_columns: set[str]
) -> list[dict]:
    """Load computed properties for a type and re-derive each one's referenced
    columns (so a masked-column check can be applied at query time). A stored
    function that no longer validates (e.g. its column was removed) is skipped
    rather than breaking every object read."""
    specs: list[dict] = []
    for fn in await get_functions(session, object_type):
        try:
            cols = validate_function_expression(fn.expression, allowed_columns)
        except BadFunctionExpression:
            continue
        specs.append({"name": fn.name, "expression": fn.expression, "columns": cols})
    return specs
