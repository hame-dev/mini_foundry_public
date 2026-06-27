"""Identifier safety.

Used everywhere we interpolate a table/column/schema name into SQL without
binding (table/column names cannot be bound). Anything that doesn't match
`[A-Za-z_][A-Za-z0-9_]*` is refused with `UnsafeIdentifier`.

Pulled out of the v0.4 dashboards.data_binding so that v0.7 ontology code
and the v0.8 DuckDB runner can reuse it without a circular import.
"""
import re


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class UnsafeIdentifier(ValueError):
    pass


def is_safe_ident(name: str) -> bool:
    return isinstance(name, str) and bool(_IDENT_RE.match(name))


def assert_safe_ident(name: str) -> None:
    if not is_safe_ident(name):
        raise UnsafeIdentifier(f"unsafe identifier: {name!r}")


def quote_ident(name: str) -> str:
    assert_safe_ident(name)
    return f'"{name}"'
