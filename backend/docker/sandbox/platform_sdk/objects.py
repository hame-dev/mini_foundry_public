"""platform_sdk.objects — read-only ontology access inside the sandbox.

The container runs with --network=none, so it cannot call the backend. Instead
the worker ships a read-only ontology snapshot (object types + their backing
dataset) into /workspace alongside the permitted dataset parquet files. This
module resolves objects against that snapshot using pandas — no network needed.

Usage inside a cell / transform:
    customer = platform_sdk.objects.Customer.get("C-1001")
    actives  = platform_sdk.objects.Customer.search(status="active")
    everyone = platform_sdk.objects.Customer.list(limit=100)
"""
from __future__ import annotations

from typing import Any

import platform_sdk as _sdk

_NOT_CONFIGURED_MSG = (
    "platform_sdk.objects has no ontology snapshot mounted for this run. Attach "
    "the object type's backing dataset to the cell/transform so its data is "
    "available, then access it via platform_sdk.objects.<TypeName>."
)


def _types() -> dict[str, dict[str, Any]]:
    onto = getattr(_sdk, "_ONTOLOGY", None) or {}
    return {t["type_name"]: t for t in onto.get("object_types", [])}


class _ObjectType:
    """Read-only accessor for a single ontology object type."""

    def __init__(self, spec: dict[str, Any]):
        self._spec = spec
        self.type_name: str = spec["type_name"]
        self.primary_key: str = spec["primary_key"]
        self.display_name_column: str | None = spec.get("display_name_column")
        self._dataset_name: str | None = spec.get("dataset_name")

    def _frame(self):
        if not self._dataset_name:
            raise NotImplementedError(
                f"object type {self.type_name!r} has no backing dataset mounted; "
                "attach it to this run to query it."
            )
        return _sdk.load_table(self._dataset_name)

    def list(self, limit: int | None = None) -> list[dict[str, Any]]:
        df = self._frame()
        if limit is not None:
            df = df.head(limit)
        return df.to_dict("records")

    def get(self, primary_key_value: Any) -> dict[str, Any] | None:
        df = self._frame()
        if self.primary_key not in df.columns:
            raise KeyError(
                f"primary key {self.primary_key!r} not present in {self.type_name} data"
            )
        match = df[df[self.primary_key] == primary_key_value]
        if match.empty:
            return None
        return match.iloc[0].to_dict()

    def search(self, **filters: Any) -> list[dict[str, Any]]:
        df = self._frame()
        for col, value in filters.items():
            if col not in df.columns:
                raise KeyError(f"column {col!r} not present in {self.type_name} data")
            df = df[df[col] == value]
        return df.to_dict("records")

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<ontology object type {self.type_name!r} pk={self.primary_key!r}>"


def __getattr__(name: str):  # PEP 562 lazy attribute on module
    types = _types()
    if name in types:
        return _ObjectType(types[name])
    if not types:
        raise NotImplementedError(_NOT_CONFIGURED_MSG)
    raise AttributeError(
        f"ontology object type {name!r} not found. Available: {sorted(types)}"
    )
