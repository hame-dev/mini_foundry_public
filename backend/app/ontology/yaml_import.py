"""Parse README §12 shape YAML into ontology rows.

Expected shape:

  objects:
    Customer:
      table: customers      # resolved to a Dataset by table_name (must be unique)
      primary_key: id
      display_name: name
      properties:
        id: integer
        name: text
      relationships:
        orders:
          target: Order
          type: one_to_many
          source_key: id
          target_key: customer_id
"""
from __future__ import annotations

from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.models import Dataset
from app.ontology.models import (
    CARDINALITIES,
    OntologyObject,
    OntologyRelationship,
)
from app.util.identifiers import assert_safe_ident


class YamlImportError(ValueError):
    pass


async def _find_dataset_by_table(session: AsyncSession, table_name: str) -> Dataset | None:
    result = await session.execute(select(Dataset).where(Dataset.table_name == table_name))
    rows = result.scalars().all()
    if len(rows) != 1:
        return None
    return rows[0]


def _properties_from_yaml(props: dict[str, str]) -> list[dict[str, str]]:
    return [{"name": name, "column": name, "type": ptype} for name, ptype in props.items()]


async def import_yaml(session: AsyncSession, yaml_text: str) -> dict[str, int]:
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise YamlImportError(f"invalid YAML: {e}")

    if not isinstance(data, dict) or "objects" not in data:
        raise YamlImportError("YAML must have a top-level 'objects' mapping")

    objects: dict[str, Any] = data["objects"]
    created_objects = 0
    created_relationships = 0

    type_to_object: dict[str, OntologyObject] = {}

    for type_name, spec in objects.items():
        assert_safe_ident(type_name)
        table_name = spec.get("table")
        if not table_name:
            raise YamlImportError(f"{type_name}: missing 'table'")
        ds = await _find_dataset_by_table(session, table_name)
        if ds is None:
            raise YamlImportError(
                f"{type_name}: table {table_name!r} not found or ambiguous in datasets"
            )

        pk = spec.get("primary_key", "id")
        assert_safe_ident(pk)
        display = spec.get("display_name")
        properties = _properties_from_yaml(spec.get("properties", {}))
        for p in properties:
            assert_safe_ident(p["column"])

        existing = (await session.execute(
            select(OntologyObject).where(OntologyObject.type_name == type_name)
        )).scalar_one_or_none()
        if existing is None:
            obj = OntologyObject(
                type_name=type_name,
                dataset_id=ds.id,
                primary_key=pk,
                display_name_column=display,
                properties=properties,
                description=spec.get("description"),
            )
            session.add(obj)
            created_objects += 1
        else:
            existing.dataset_id = ds.id
            existing.primary_key = pk
            existing.display_name_column = display
            existing.properties = properties
            existing.description = spec.get("description")
            obj = existing
        await session.flush()
        type_to_object[type_name] = obj

    # Second pass for relationships (now all targets exist)
    for type_name, spec in objects.items():
        for rel_name, rel_spec in (spec.get("relationships") or {}).items():
            assert_safe_ident(rel_name)
            target = rel_spec.get("target")
            if target not in type_to_object:
                raise YamlImportError(f"{type_name}.{rel_name}: unknown target {target!r}")
            card = rel_spec.get("type", "one_to_many")
            if card not in CARDINALITIES:
                raise YamlImportError(f"{type_name}.{rel_name}: unknown cardinality {card!r}")
            source_key = rel_spec.get("source_key", "id")
            target_key = rel_spec.get("target_key")
            if not target_key:
                raise YamlImportError(f"{type_name}.{rel_name}: missing target_key")
            assert_safe_ident(source_key)
            assert_safe_ident(target_key)

            existing = (await session.execute(
                select(OntologyRelationship).where(
                    OntologyRelationship.source_type == type_name,
                    OntologyRelationship.name == rel_name,
                )
            )).scalar_one_or_none()
            if existing is None:
                session.add(OntologyRelationship(
                    source_type=type_name, target_type=target, name=rel_name,
                    cardinality=card, source_key=source_key, target_key=target_key,
                ))
                created_relationships += 1
            else:
                existing.target_type = target
                existing.cardinality = card
                existing.source_key = source_key
                existing.target_key = target_key
            await session.flush()

    return {"objects": created_objects, "relationships": created_relationships}
