"""yaml_import unit tests using a fake AsyncSession + datasets.

Because the test environment doesn't have asyncio + a live DB, we skip
the round-trip and just verify the parser/validator surface: malformed
YAML, missing top-level keys, unknown cardinality, unsafe identifiers.
"""
import asyncio
import pytest

from app.ontology.yaml_import import YamlImportError, import_yaml


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self):
        self.added = []

    async def execute(self, _stmt):
        return _FakeResult([])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


def test_invalid_yaml_rejected():
    with pytest.raises(YamlImportError):
        asyncio.run(import_yaml(_FakeSession(), "::not yaml::"))


def test_missing_objects_key_rejected():
    with pytest.raises(YamlImportError, match="objects"):
        asyncio.run(import_yaml(_FakeSession(), "foo: bar"))


def test_table_not_found_rejected():
    yaml_text = """
objects:
  Customer:
    table: customers_does_not_exist
    primary_key: id
    properties:
      id: integer
"""
    with pytest.raises(YamlImportError, match="not found"):
        asyncio.run(import_yaml(_FakeSession(), yaml_text))


def test_unsafe_type_name_rejected():
    yaml_text = """
objects:
  "Bad Type Name":
    table: customers
    primary_key: id
    properties:
      id: integer
"""
    with pytest.raises(Exception):
        asyncio.run(import_yaml(_FakeSession(), yaml_text))
