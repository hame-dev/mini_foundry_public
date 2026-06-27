import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.audit.logger import log_event
from app.data.models import Dataset
from app.deps import AdminDep, CurrentUserDep, SessionDep
from app.ontology import object_sets, service
from app.ontology.functions import BadFunctionExpression, validate_function_expression
from app.ontology.models import (
    CARDINALITIES,
    OntologyFunction,
    OntologyLayout,
    OntologyObject,
    OntologyObjectSet,
    OntologyRelationship,
)
from app.ontology.yaml_import import YamlImportError, import_yaml
from app.permissions.enforcement import PermissionDenied, effective_capabilities_for_object
from app.platform.service import get_resource_for_object, register_resource_version, upsert_resource
from app.util.identifiers import UnsafeIdentifier, assert_safe_ident


router = APIRouter(prefix="/ontology", tags=["ontology"])
admin_router = APIRouter(prefix="/admin/ontology", tags=["ontology"])
objects_router = APIRouter(prefix="/objects", tags=["ontology"])


# ----- pydantic ----------------------------------------------------------


class PropertyIn(BaseModel):
    name: str
    column: str
    type: str | None = None


class ObjectIn(BaseModel):
    type_name: str
    dataset_id: uuid.UUID
    primary_key: str
    display_name_column: str | None = None
    properties: list[PropertyIn] = []
    description: str | None = None
    branch_name: str = "main"


class ObjectOut(BaseModel):
    id: str
    type_name: str
    dataset_id: str
    primary_key: str
    display_name_column: str | None
    properties: list[dict]
    description: str | None


class RelationshipIn(BaseModel):
    source_type: str
    target_type: str
    name: str
    cardinality: str
    source_key: str
    target_key: str
    branch_name: str = "main"


class RelationshipOut(BaseModel):
    id: str
    source_type: str
    target_type: str
    name: str
    cardinality: str
    source_key: str
    target_key: str


class FunctionIn(BaseModel):
    name: str
    expression: str
    return_type: str | None = None
    description: str | None = None


class FunctionOut(BaseModel):
    id: str
    object_type: str
    name: str
    expression: str
    return_type: str | None
    description: str | None


class FilterPredicate(BaseModel):
    column: str
    op: str
    value: Any | None = None


class ObjectSetIn(BaseModel):
    name: str
    object_type: str
    filters: list[FilterPredicate] = []
    description: str | None = None
    branch_name: str = "main"


class ObjectSetOut(BaseModel):
    id: str
    name: str
    object_type: str
    filters: list[dict]
    description: str | None
    owner_id: str | None


class ObjectSetQueryIn(BaseModel):
    limit: int = 100
    offset: int = 0
    sort_by: str | None = None
    sort_dir: str = "asc"


class AdHocQueryIn(BaseModel):
    filters: list[FilterPredicate] = []
    limit: int = 100
    offset: int = 0
    sort_by: str | None = None
    sort_dir: str = "asc"


def _fn_out(f: OntologyFunction) -> FunctionOut:
    return FunctionOut(
        id=str(f.id), object_type=f.object_type, name=f.name, expression=f.expression,
        return_type=f.return_type, description=f.description,
    )


def _set_out(s: OntologyObjectSet) -> ObjectSetOut:
    return ObjectSetOut(
        id=str(s.id), name=s.name, object_type=s.object_type, filters=s.filters or [],
        description=s.description, owner_id=str(s.owner_id) if s.owner_id else None,
    )


def _obj_out(o: OntologyObject) -> ObjectOut:
    return ObjectOut(
        id=str(o.id), type_name=o.type_name, dataset_id=str(o.dataset_id),
        primary_key=o.primary_key, display_name_column=o.display_name_column,
        properties=o.properties or [], description=o.description,
    )


def _rel_out(r: OntologyRelationship) -> RelationshipOut:
    return RelationshipOut(
        id=str(r.id), source_type=r.source_type, target_type=r.target_type,
        name=r.name, cardinality=r.cardinality, source_key=r.source_key, target_key=r.target_key,
    )


async def _register_ontology_object_version(session: SessionDep, obj: OntologyObject, user_id: uuid.UUID, branch_name: str, kind: str) -> None:
    resource = await upsert_resource(
        session,
        resource_type="ontology_object_type",
        object_id=obj.id,
        name=obj.type_name,
        owner_user_id=user_id,
        metadata={"dataset_id": str(obj.dataset_id), "primary_key": obj.primary_key},
    )
    await register_resource_version(
        session,
        resource=resource,
        created_by=user_id,
        branch_name=branch_name or "main",
        manifest={"kind": kind, "branch_name": branch_name or "main", "object": _obj_out(obj).model_dump()},
    )


async def _register_relationship_version(session: SessionDep, rel: OntologyRelationship, user_id: uuid.UUID, branch_name: str, kind: str) -> None:
    resource = await upsert_resource(
        session,
        resource_type="ontology_relationship",
        object_id=rel.id,
        name=rel.name,
        owner_user_id=user_id,
        metadata={"source_type": rel.source_type, "target_type": rel.target_type, "cardinality": rel.cardinality},
    )
    await register_resource_version(
        session,
        resource=resource,
        created_by=user_id,
        branch_name=branch_name or "main",
        manifest={"kind": kind, "branch_name": branch_name or "main", "relationship": _rel_out(rel).model_dump()},
    )


# ----- public read -------------------------------------------------------


@router.get("/graph")
async def get_ontology_graph(session: SessionDep, user: CurrentUserDep) -> dict[str, Any]:
    """Return the ontology as a node/edge graph for the visual editor.

    Each user's stored positions are merged in if present so the canvas
    remembers placement across reloads.
    """
    objs_q = await session.execute(select(OntologyObject))
    rels_q = await session.execute(select(OntologyRelationship))
    objs = list(objs_q.scalars().all())
    rels = list(rels_q.scalars().all())

    layout_q = await session.execute(
        select(OntologyLayout).where(OntologyLayout.user_id == user.id)
    )
    layout = layout_q.scalar_one_or_none()
    positions: dict[str, Any] = (layout.positions or {}) if layout else {}
    viewport: dict[str, Any] = (layout.viewport or {}) if layout else {}

    nodes = [
        {
            "id": str(o.id),
            "type_name": o.type_name,
            "dataset_id": str(o.dataset_id),
            "primary_key": o.primary_key,
            "display_name_column": o.display_name_column,
            "properties": o.properties or [],
            "description": o.description,
            "position": positions.get(str(o.id)) or {},
        }
        for o in objs
    ]
    edges = [
        {
            "id": str(r.id),
            "source": r.source_type,
            "target": r.target_type,
            "name": r.name,
            "cardinality": r.cardinality,
            "source_key": r.source_key,
            "target_key": r.target_key,
        }
        for r in rels
    ]
    return {"nodes": nodes, "edges": edges, "viewport": viewport}


class LayoutIn(BaseModel):
    positions: dict[str, dict[str, float]] = {}
    viewport: dict[str, float] = {}


@router.post("/layout")
async def save_ontology_layout(
    payload: LayoutIn, session: SessionDep, user: CurrentUserDep
) -> dict:
    row_q = await session.execute(select(OntologyLayout).where(OntologyLayout.user_id == user.id))
    row = row_q.scalar_one_or_none()
    if row is None:
        row = OntologyLayout(user_id=user.id, positions=payload.positions, viewport=payload.viewport)
        session.add(row)
    else:
        row.positions = payload.positions
        row.viewport = payload.viewport
    await session.commit()
    return {"ok": True}


@router.get("/objects", response_model=list[ObjectOut])
async def list_objects(session: SessionDep, _: CurrentUserDep) -> list[ObjectOut]:
    rows = await service.list_objects(session)
    return [_obj_out(o) for o in rows]


@router.get("/objects/{type_name}")
async def get_object_schema(
    type_name: str, session: SessionDep, _: CurrentUserDep,
) -> dict:
    obj = await service.get_object(session, type_name)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object type not found")
    rels = await service.get_relationships(session, type_name)
    return {
        "object": _obj_out(obj).model_dump(),
        "relationships": [_rel_out(r).model_dump() for r in rels],
    }


@router.get("/object-types/{type_name}/detail")
async def get_object_type_detail(
    type_name: str, session: SessionDep, _: CurrentUserDep,
) -> dict:
    obj = await service.get_object(session, type_name)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object type not found")
    rels = await service.get_relationships(session, type_name)
    dataset = await session.get(Dataset, obj.dataset_id)
    dependents = [
        {
            "type": "relationship",
            "name": r.name,
            "target": r.target_type if r.source_type == type_name else r.source_type,
            "cardinality": r.cardinality,
        }
        for r in rels
    ]
    link_graph = {
        "nodes": [{"id": type_name, "label": type_name}]
        + [{"id": d["target"], "label": d["target"]} for d in dependents],
        "edges": [
            {"source": type_name, "target": d["target"], "label": d["name"], "cardinality": d["cardinality"]}
            for d in dependents
        ],
    }
    return {
        "object": _obj_out(obj).model_dump(),
        "properties": obj.properties or [],
        "relationships": [_rel_out(r).model_dump() for r in rels],
        "action_types": [],
        "dependents": dependents,
        "datasets": [
            {
                "id": str(dataset.id),
                "name": dataset.name,
                "schema_name": dataset.schema_name,
                "table_name": dataset.table_name,
                "row_count": dataset.row_count,
            }
        ] if dataset else [],
        "usage": {"views_30d": 0, "actions_30d": 0, "dashboards": 0},
        "link_graph": link_graph,
    }


# ----- functions on objects (read) ---------------------------------------


@router.get("/objects/{type_name}/functions", response_model=list[FunctionOut])
async def list_functions(type_name: str, session: SessionDep, _: CurrentUserDep) -> list[FunctionOut]:
    rows = await object_sets.get_functions(session, type_name)
    return [_fn_out(f) for f in rows]


# ----- object sets -------------------------------------------------------


async def _object_set_visible(session: SessionDep, user, s: OntologyObjectSet) -> bool:
    if s.owner_id == user.id:
        return True
    # effective_resource_capabilities short-circuits admins/owners to full caps.
    caps = await effective_capabilities_for_object(session, user, "ontology_object_set", s.id)
    return "view_metadata" in caps or "manage" in caps


async def _object_set_manageable(session: SessionDep, user, s: OntologyObjectSet) -> bool:
    if s.owner_id == user.id:
        return True
    caps = await effective_capabilities_for_object(session, user, "ontology_object_set", s.id)
    return "manage" in caps


@router.get("/object-sets", response_model=list[ObjectSetOut])
async def list_object_sets(
    session: SessionDep, user: CurrentUserDep, object_type: str | None = None,
) -> list[ObjectSetOut]:
    stmt = select(OntologyObjectSet).order_by(OntologyObjectSet.name)
    if object_type:
        stmt = stmt.where(OntologyObjectSet.object_type == object_type)
    rows = list((await session.execute(stmt)).scalars().all())
    visible = [s for s in rows if await _object_set_visible(session, user, s)]
    return [_set_out(s) for s in visible]


@router.post("/object-sets", response_model=ObjectSetOut)
async def create_object_set(payload: ObjectSetIn, session: SessionDep, user: CurrentUserDep) -> ObjectSetOut:
    obj = await service.get_object(session, payload.object_type)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object type not found")
    # Validate the filter columns up-front so a saved set can never hold an
    # ungoverned/unsafe predicate.
    try:
        object_sets.build_filter_where([p.model_dump() for p in payload.filters], service.allowed_columns(obj))
    except object_sets.BadFilter as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    s = OntologyObjectSet(
        name=payload.name,
        object_type=payload.object_type,
        filters=[p.model_dump() for p in payload.filters],
        description=payload.description,
        owner_id=user.id,
        branch_name=payload.branch_name or "main",
    )
    session.add(s)
    await session.flush()
    resource = await upsert_resource(
        session, resource_type="ontology_object_set", object_id=s.id, name=s.name,
        owner_user_id=user.id, metadata={"object_type": s.object_type},
    )
    await register_resource_version(
        session, resource=resource, created_by=user.id, branch_name=s.branch_name,
        manifest={"kind": "ontology_object_set_created", "object_set": _set_out(s).model_dump()},
    )
    await log_event(
        session, user=user, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_object_set", resource_id=str(s.id),
        input_summary={"action": "create", "name": s.name, "object_type": s.object_type},
    )
    await session.commit()
    return _set_out(s)


@router.get("/object-sets/{set_id}", response_model=ObjectSetOut)
async def get_object_set(set_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> ObjectSetOut:
    s = await session.get(OntologyObjectSet, set_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object set not found")
    if not await _object_set_visible(session, user, s):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not authorized to view this object set")
    return _set_out(s)


@router.put("/object-sets/{set_id}", response_model=ObjectSetOut)
async def update_object_set(
    set_id: uuid.UUID, payload: ObjectSetIn, session: SessionDep, user: CurrentUserDep,
) -> ObjectSetOut:
    s = await session.get(OntologyObjectSet, set_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object set not found")
    if not await _object_set_manageable(session, user, s):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not authorized to edit this object set")
    obj = await service.get_object(session, payload.object_type)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object type not found")
    try:
        object_sets.build_filter_where([p.model_dump() for p in payload.filters], service.allowed_columns(obj))
    except object_sets.BadFilter as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    s.name = payload.name
    s.object_type = payload.object_type
    s.filters = [p.model_dump() for p in payload.filters]
    s.description = payload.description
    await log_event(
        session, user=user, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_object_set", resource_id=str(s.id),
        input_summary={"action": "update"},
    )
    await session.commit()
    return _set_out(s)


@router.delete("/object-sets/{set_id}")
async def delete_object_set(set_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    s = await session.get(OntologyObjectSet, set_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object set not found")
    if not await _object_set_manageable(session, user, s):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not authorized to delete this object set")
    await session.delete(s)
    await log_event(
        session, user=user, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_object_set", resource_id=str(set_id),
        input_summary={"action": "delete"},
    )
    await session.commit()
    return {"ok": True}


@router.post("/object-sets/{set_id}/query")
async def query_object_set(
    set_id: uuid.UUID, payload: ObjectSetQueryIn, session: SessionDep, user: CurrentUserDep,
) -> dict:
    s = await session.get(OntologyObjectSet, set_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object set not found")
    if not await _object_set_visible(session, user, s):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not authorized to view this object set")
    try:
        result = await object_sets.query_object_set(
            session, user, s.object_type, s.filters or [],
            limit=payload.limit, offset=payload.offset,
            sort_by=payload.sort_by, sort_dir=payload.sort_dir,
            audit_resource_id=str(s.id),
        )
    except service.OntologyNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except object_sets.BadFilter as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except PermissionDenied as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    return result


# ----- public load -------------------------------------------------------


@objects_router.post("/{type_name}/query")
async def query_objects_adhoc(
    type_name: str, payload: AdHocQueryIn, session: SessionDep, user: CurrentUserDep,
) -> dict:
    try:
        return await object_sets.query_object_set(
            session, user, type_name, [p.model_dump() for p in payload.filters],
            limit=payload.limit, offset=payload.offset,
            sort_by=payload.sort_by, sort_dir=payload.sort_dir,
        )
    except service.OntologyNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except object_sets.BadFilter as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except PermissionDenied as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))


@objects_router.get("/{type_name}/{object_id}")
async def get_object_row(
    type_name: str, object_id: str, session: SessionDep, user: CurrentUserDep,
) -> dict:
    try:
        return await service.load_object(session, user, type_name, object_id)
    except service.OntologyNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except PermissionDenied as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))


@objects_router.get("/{type_name}/{object_id}/related/{rel_name}")
async def get_related(
    type_name: str, object_id: str, rel_name: str,
    session: SessionDep, user: CurrentUserDep,
) -> dict:
    try:
        return await service.load_related(session, user, type_name, object_id, rel_name)
    except service.OntologyNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except PermissionDenied as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))


# ----- admin CRUD --------------------------------------------------------


def _validate_ident_or_400(name: str, label: str) -> None:
    try:
        assert_safe_ident(name)
    except UnsafeIdentifier:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsafe {label}: {name!r}")


@admin_router.post("/objects", response_model=ObjectOut)
async def create_object(payload: ObjectIn, session: SessionDep, admin: AdminDep) -> ObjectOut:
    _validate_ident_or_400(payload.type_name, "type_name")
    _validate_ident_or_400(payload.primary_key, "primary_key")
    for p in payload.properties:
        _validate_ident_or_400(p.column, "property.column")
    obj = OntologyObject(
        type_name=payload.type_name,
        dataset_id=payload.dataset_id,
        primary_key=payload.primary_key,
        display_name_column=payload.display_name_column,
        properties=[p.model_dump() for p in payload.properties],
        description=payload.description,
    )
    session.add(obj)
    await session.flush()
    await _register_ontology_object_version(session, obj, admin.id, payload.branch_name, "ontology_object_created")
    await log_event(
        session, user=admin, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_object", resource_id=str(obj.id),
        input_summary={"action": "create", "type_name": payload.type_name, "branch_name": payload.branch_name},
    )
    await session.commit()
    return _obj_out(obj)


@admin_router.put("/objects/{object_id}", response_model=ObjectOut)
async def update_object(
    object_id: uuid.UUID, payload: ObjectIn, session: SessionDep, admin: AdminDep,
) -> ObjectOut:
    obj = await session.get(OntologyObject, object_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object not found")
    _validate_ident_or_400(payload.type_name, "type_name")
    _validate_ident_or_400(payload.primary_key, "primary_key")
    obj.type_name = payload.type_name
    obj.dataset_id = payload.dataset_id
    obj.primary_key = payload.primary_key
    obj.display_name_column = payload.display_name_column
    obj.properties = [p.model_dump() for p in payload.properties]
    obj.description = payload.description
    await _register_ontology_object_version(session, obj, admin.id, payload.branch_name, "ontology_object_updated")
    await log_event(
        session, user=admin, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_object", resource_id=str(obj.id),
        input_summary={"action": "update", "branch_name": payload.branch_name},
    )
    await session.commit()
    return _obj_out(obj)


@admin_router.delete("/objects/{object_id}")
async def delete_object(
    object_id: uuid.UUID, session: SessionDep, admin: AdminDep, branch_name: str = "main",
) -> dict:
    obj = await session.get(OntologyObject, object_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object not found")
    await _register_ontology_object_version(session, obj, admin.id, branch_name, "ontology_object_deleted")
    await session.delete(obj)
    await log_event(
        session, user=admin, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_object", resource_id=str(object_id),
        input_summary={"action": "delete"},
    )
    await session.commit()
    return {"ok": True}


@admin_router.post("/relationships", response_model=RelationshipOut)
async def create_relationship(
    payload: RelationshipIn, session: SessionDep, admin: AdminDep,
) -> RelationshipOut:
    if payload.cardinality not in CARDINALITIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown cardinality: {payload.cardinality}")
    _validate_ident_or_400(payload.source_key, "source_key")
    _validate_ident_or_400(payload.target_key, "target_key")
    rel = OntologyRelationship(**payload.model_dump())
    session.add(rel)
    await session.flush()
    await _register_relationship_version(session, rel, admin.id, payload.branch_name, "ontology_relationship_created")
    await log_event(
        session, user=admin, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_relationship", resource_id=str(rel.id),
        input_summary={"action": "create", **payload.model_dump()},
    )
    await session.commit()
    return _rel_out(rel)


@admin_router.delete("/relationships/{rel_id}")
async def delete_relationship(
    rel_id: uuid.UUID, session: SessionDep, admin: AdminDep, branch_name: str = "main",
) -> dict:
    rel = await session.get(OntologyRelationship, rel_id)
    if rel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "relationship not found")
    await _register_relationship_version(session, rel, admin.id, branch_name, "ontology_relationship_deleted")
    await session.delete(rel)
    await session.commit()
    return {"ok": True}


@admin_router.post("/objects/{type_name}/functions", response_model=FunctionOut)
async def create_function(
    type_name: str, payload: FunctionIn, session: SessionDep, admin: AdminDep,
) -> FunctionOut:
    obj = await service.get_object(session, type_name)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object type not found")
    _validate_ident_or_400(payload.name, "function name")
    try:
        validate_function_expression(payload.expression, service.allowed_columns(obj))
    except BadFunctionExpression as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    fn = OntologyFunction(
        object_type=type_name,
        name=payload.name,
        expression=payload.expression,
        return_type=payload.return_type,
        description=payload.description,
    )
    session.add(fn)
    await session.flush()
    await log_event(
        session, user=admin, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_function", resource_id=str(fn.id),
        input_summary={"action": "create", "object_type": type_name, "name": payload.name},
    )
    await session.commit()
    return _fn_out(fn)


@admin_router.put("/functions/{function_id}", response_model=FunctionOut)
async def update_function(
    function_id: uuid.UUID, payload: FunctionIn, session: SessionDep, admin: AdminDep,
) -> FunctionOut:
    fn = await session.get(OntologyFunction, function_id)
    if fn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "function not found")
    obj = await service.get_object(session, fn.object_type)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "object type not found")
    _validate_ident_or_400(payload.name, "function name")
    try:
        validate_function_expression(payload.expression, service.allowed_columns(obj))
    except BadFunctionExpression as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    fn.name = payload.name
    fn.expression = payload.expression
    fn.return_type = payload.return_type
    fn.description = payload.description
    await log_event(
        session, user=admin, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_function", resource_id=str(fn.id),
        input_summary={"action": "update"},
    )
    await session.commit()
    return _fn_out(fn)


@admin_router.delete("/functions/{function_id}")
async def delete_function(function_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    fn = await session.get(OntologyFunction, function_id)
    if fn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "function not found")
    await session.delete(fn)
    await log_event(
        session, user=admin, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_function", resource_id=str(function_id),
        input_summary={"action": "delete"},
    )
    await session.commit()
    return {"ok": True}


@admin_router.post("/import-yaml")
async def import_yaml_route(
    payload: dict, session: SessionDep, admin: AdminDep,
) -> dict:
    yaml_text = payload.get("yaml")
    if not isinstance(yaml_text, str):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "yaml string required")
    try:
        result = await import_yaml(session, yaml_text)
    except YamlImportError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    await log_event(
        session, user=admin, event_type="ONTOLOGY_EDITED",
        resource_type="ontology", input_summary={"action": "import_yaml"},
        output_summary=result,
    )
    await session.commit()
    return result
