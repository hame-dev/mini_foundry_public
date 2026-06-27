from abc import ABC, abstractmethod
from typing import Any


class Connector(ABC):
    """Abstract connector matching README §18."""

    @abstractmethod
    def test_connection(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def discover_schema(self) -> list[dict[str, Any]]:
        """Return [{schema, table, columns: [{name, type, sample}], row_count}]."""
        ...

    @abstractmethod
    def preview(self, schema: str, table: str, limit: int = 100) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def query(self, sql: str, params: dict | None = None) -> list[dict[str, Any]]:
        ...
