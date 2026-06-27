"""Ontology resolution: load an object by id, load related objects.

Reuses the governed query service for permissions, row policies, and masking.
Identifier safety via app.util.identifiers — ontology metadata is admin-
controlled but we still validate every column/table name before splicing.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.data.models import Dataset
from app.governed_query.service import governed_query
from app.ontology.functions import build_function_select, resolve_function_specs
from app.ontology.models import OntologyObject, OntologyRelationship
from app.permissions.enforcement import require_object_capability
from app.permissions.masking import resolve_column_masks
from app.util.identifiers import UnsafeIdentifier, assert_safe_ident, quote_ident


class OntologyNotFound(LookupError):
    pass


async def get_object(session: AsyncSession, type_name: str) -> OntologyObject | None:
    result = await session.execute(
        select(OntologyObject).where(OntologyObject.type_name == type_name)
    )
    return result.scalar_one_or_none()


async def list_objects(session: AsyncSession) -> list[OntologyObject]:
    result = await session.execute(select(OntologyObject).order_by(OntologyObject.type_name))
    return list(result.scalars().all())


async def get_relationships(session: AsyncSession, source_type: str) -> list[OntologyRelationship]:
    result = await session.execute(
        select(OntologyRelationship).where(OntologyRelationship.source_type == source_type)
    )
    return list(result.scalars().all())


async def get_relationship(
    session: AsyncSession, source_type: str, name: str
) -> OntologyRelationship | None:
    result = await session.execute(
        select(OntologyRelationship).where(
            OntologyRelationship.source_type == source_type,
            OntologyRelationship.name == name,
        )
    )
    return result.scalar_one_or_none()


def allowed_columns(obj: OntologyObject) -> set[str]:
    """Columns a user may reference in a filter or computed property: the object
    type's declared property columns plus its primary key and display column."""
    cols = {p.get("column") for p in (obj.properties or []) if p.get("column")}
    cols.add(obj.primary_key)
    if obj.display_name_column:
        cols.add(obj.display_name_column)
    return cols


def _project(row: dict, properties: list[dict]) -> dict[str, Any]:
    """Project the raw row through the ontology's property list. Each entry
    is {name, column, type?}. Unknown columns silently become None so a
    drift-tolerant frontend can still render the object."""
    out: dict[str, Any] = {}
    for spec in properties:
        name = spec.get("name") or spec.get("column")
        col = spec.get("column", name)
        out[name] = row.get(col)
    return out


async def load_object(
    session: AsyncSession, user: User, type_name: str, object_id: Any
) -> dict[str, Any]:
    obj = await get_object(session, type_name)
    if obj is None:
        raise OntologyNotFound(f"unknown object type: {type_name}")
    ds = await session.get(Dataset, obj.dataset_id)
    if ds is None:
        raise OntologyNotFound(f"backing dataset missing for {type_name}")

    await require_object_capability(session, user, "dataset", ds.id, "view_data")

    assert_safe_ident(ds.schema_name)
    assert_safe_ident(ds.table_name)
    assert_safe_ident(obj.primary_key)

    # Splice in computed properties (mask-aware: a function over a masked column
    # is redacted to NULL so derived values can't leak masked data).
    masks = await resolve_column_masks(session, user.id, ds.id)
    fn_specs = await resolve_function_specs(session, type_name, allowed_columns(obj))
    fn_fragments, fn_names = build_function_select(fn_specs, set(masks.keys()))
    select_list = "*" if not fn_fragments else "*, " + ", ".join(fn_fragments)

    sql = (
        f"SELECT {select_list} FROM {quote_ident(ds.schema_name)}.{quote_ident(ds.table_name)} "
        f"WHERE {quote_ident(obj.primary_key)} = :id LIMIT 1"
    )
    result = await governed_query(
        session,
        user,
        sql,
        params={"id": object_id},
        dataset_ids=[ds.id],
        capability="view_data",
        audit_resource_type="ontology_object",
        audit_resource_id=str(obj.id),
    )
    if not result["rows"]:
        raise OntologyNotFound(f"{type_name} with id={object_id} not found")
    row = result["rows"][0]

    return {
        "type": type_name,
        "id": object_id,
        "display_name": row.get(obj.display_name_column) if obj.display_name_column else None,
        "properties": _project(row, obj.properties or []),
        "functions": {n: row.get(n) for n in fn_names if n in row},
        "raw": row,
    }


async def load_related(
    session: AsyncSession, user: User, source_type: str, source_id: Any, rel_name: str
) -> dict[str, Any]:
    rel = await get_relationship(session, source_type, rel_name)
    if rel is None:
        raise OntologyNotFound(f"relationship {source_type}.{rel_name} not found")
    target = await get_object(session, rel.target_type)
    if target is None:
        raise OntologyNotFound(f"target object {rel.target_type} not found")
    target_ds = await session.get(Dataset, target.dataset_id)
    if target_ds is None:
        raise OntologyNotFound("target dataset missing")

    await require_object_capability(session, user, "dataset", target_ds.id, "view_data")

    assert_safe_ident(target_ds.schema_name)
    assert_safe_ident(target_ds.table_name)
    assert_safe_ident(rel.target_key)

    sql = (
        f"SELECT * FROM {quote_ident(target_ds.schema_name)}.{quote_ident(target_ds.table_name)} "
        f"WHERE {quote_ident(rel.target_key)} = :v LIMIT 500"
    )
    result = await governed_query(
        session,
        user,
        sql,
        params={"v": source_id},
        dataset_ids=[target_ds.id],
        capability="view_data",
        audit_resource_type="ontology_relationship",
        audit_resource_id=str(rel.id),
    )
    result["target_type"] = rel.target_type
    result["relationship"] = rel.name
    return result
