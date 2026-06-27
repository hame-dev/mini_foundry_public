from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.applications.models import Application, ApplicationPage
from app.audit.logger import log_event
from app.auth.service import get_user_roles
from app.deps import CurrentUserDep, SessionDep
from app.ontology.models import OntologyAction, OntologyObject
from app.permissions.enforcement import effective_capabilities_for_object, effective_resource_capabilities
from app.platform.models import LineageEdge, Resource, ResourceVersion
from app.platform.service import (
    get_resource_for_object,
    record_lineage,
    register_resource_version,
    upsert_resource,
)

router = APIRouter(prefix="/applications", tags=["applications"])


class PageIn(BaseModel):
    title: str
    page_type: str = "object_table"
    object_type: str | None = None
    config: dict[str, Any] = {}
    role_visibility: list[str] = []
    position: int = 0


class ApplicationIn(BaseModel):
    name: str
    description: str | None = None
    config: dict[str, Any] = {}
    pages: list[PageIn] = []
    branch_name: str = "main"


class PageOut(BaseModel):
    id: str
    title: str
    page_type: str
    object_type: str | None
    config: dict
    role_visibility: list
    position: int


class ApplicationOut(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str | None
    status: str
    config: dict
    pages: list[PageOut] = []
    published_at: datetime | None
    published_version: int | None = None
    created_at: datetime
    updated_at: datetime


class AppRuntimeOut(BaseModel):
    id: str
    name: str
    config: dict
    pages: list[dict]
    published_at: str | None = None
    published_version: int | None = None
    mode: str
    notices: list[dict] = []


def _page_out(p: ApplicationPage) -> PageOut:
    return PageOut(
        id=str(p.id),
        title=p.title,
        page_type=p.page_type,
        object_type=p.object_type,
        config=p.config or {},
        role_visibility=p.role_visibility or [],
        position=p.position,
    )


async def _require_app_cap(session, user, application_id: uuid.UUID, capability: str) -> Application:
    """Load an application and enforce a central ResourceACL capability.

    Mirrors the dataset pattern: the owner always has access, otherwise the
    capability (or "manage") must be granted via the resource graph.
    """
    app = await session.get(Application, application_id)
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "application not found")
    caps = await effective_capabilities_for_object(session, user, "application", application_id)
    if app.owner_id != user.id and not ({capability, "manage"} & caps):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "application not found")
    return app


async def _app_out(session: SessionDep, app: Application) -> ApplicationOut:
    pages = list((await session.execute(
        select(ApplicationPage).where(ApplicationPage.application_id == app.id).order_by(ApplicationPage.position, ApplicationPage.created_at)
    )).scalars().all())
    return ApplicationOut(
        id=str(app.id),
        name=app.name,
        description=app.description,
        owner_id=str(app.owner_id) if app.owner_id else None,
        status=app.status,
        config=app.config or {},
        pages=[_page_out(p) for p in pages],
        published_at=app.published_at,
        published_version=(app.published_config or {}).get("published_version"),
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


@router.get("", response_model=list[ApplicationOut])
async def list_applications(session: SessionDep, user: CurrentUserDep) -> list[ApplicationOut]:
    rows = list((await session.execute(
        select(Application).order_by(Application.updated_at.desc())
    )).scalars().all())
    visible: list[ApplicationOut] = []
    for app in rows:
        if app.owner_id == user.id:
            visible.append(await _app_out(session, app))
            continue
        caps = await effective_capabilities_for_object(session, user, "application", app.id)
        if {"view_metadata", "manage"} & caps:
            visible.append(await _app_out(session, app))
    return visible


@router.post("", response_model=ApplicationOut, status_code=201)
async def create_application(payload: ApplicationIn, session: SessionDep, user: CurrentUserDep) -> ApplicationOut:
    app = Application(name=payload.name, description=payload.description, owner_id=user.id, config=payload.config)
    session.add(app)
    await session.flush()
    for page in payload.pages:
        session.add(ApplicationPage(application_id=app.id, **page.model_dump()))
    await upsert_resource(
        session,
        resource_type="application",
        object_id=app.id,
        name=app.name,
        owner_user_id=user.id,
        metadata={"status": app.status},
    )
    await log_event(session, user=user, event_type="APPLICATION_EDITED", resource_type="application", resource_id=str(app.id), input_summary={"action": "create"})
    await session.commit()
    return await _app_out(session, app)


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(application_id: uuid.UUID, session: SessionDep, user: CurrentUserDep, branch_name: str | None = Query(default=None)) -> ApplicationOut:
    app = await _require_app_cap(session, user, application_id, "view_metadata")
    if branch_name and branch_name != "main":
        snapshot = await _latest_app_branch(session, app, branch_name)
        if snapshot:
            return _app_out_from_snapshot(app, snapshot)
    return await _app_out(session, app)


@router.put("/{application_id}", response_model=ApplicationOut)
async def update_application(application_id: uuid.UUID, payload: ApplicationIn, session: SessionDep, user: CurrentUserDep) -> ApplicationOut:
    app = await _require_app_cap(session, user, application_id, "edit")
    app.name = payload.name
    app.description = payload.description
    app.config = payload.config
    app.updated_at = datetime.utcnow()
    await session.execute(ApplicationPage.__table__.delete().where(ApplicationPage.application_id == app.id))
    for page in payload.pages:
        session.add(ApplicationPage(application_id=app.id, **page.model_dump()))
    await upsert_resource(session, resource_type="application", object_id=app.id, name=app.name, owner_user_id=user.id, metadata={"status": app.status})
    await _register_app_version(session, app, user.id, payload.branch_name, "application_draft_saved")
    await log_event(session, user=user, event_type="APPLICATION_EDITED", resource_type="application", resource_id=str(app.id), input_summary={"action": "update", "branch_name": payload.branch_name})
    await session.commit()
    return await _app_out(session, app)


async def _page_snapshot(session, app: Application) -> list[dict]:
    pages = list((await session.execute(
        select(ApplicationPage).where(ApplicationPage.application_id == app.id).order_by(ApplicationPage.position, ApplicationPage.created_at)
    )).scalars().all())
    return [_page_out(p).model_dump() for p in pages]


def _walk_dicts(value) -> list[dict]:
    found: list[dict] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_dicts(child))
    return found


def _uuidish(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _values_for_keys(payload, keys: set[str]) -> list[str]:
    values: list[str] = []
    for node in _walk_dicts(payload):
        for key, value in node.items():
            if key not in keys:
                continue
            if isinstance(value, list):
                values.extend(str(v) for v in value if v)
            elif value:
                values.append(str(value))
    return values


def _app_reference_payload(pages: list[dict], config: dict | None = None) -> dict:
    return {"pages": pages, "config": config or {}}


async def _resource_by_object(session, resource_type: str, object_id) -> Resource | None:
    oid = _uuidish(object_id)
    if oid is None:
        return None
    return await get_resource_for_object(session, resource_type, oid)


async def _record_ref(session, *, app_resource: Resource, source_resource: Resource | None, edge_type: str, metadata: dict, have: set[tuple[uuid.UUID, str]]) -> None:
    if source_resource is None or (source_resource.id, edge_type) in have:
        return
    await record_lineage(session, source_resource_id=source_resource.id, target_resource_id=app_resource.id, edge_type=edge_type, metadata=metadata)
    have.add((source_resource.id, edge_type))


async def _record_app_lineage(session, app: Application, pages: list[dict]) -> None:
    """Record edges from referenced object types / datasets to the application.

    De-dupes per (source_resource, edge_type) so republishing does not pile up
    duplicate edges. Dependencies that can't be resolved are skipped.
    """
    app_resource = await get_resource_for_object(session, "application", app.id)
    if app_resource is None:
        return
    existing = (
        await session.execute(
            select(LineageEdge.source_resource_id, LineageEdge.edge_type).where(
                LineageEdge.target_resource_id == app_resource.id
            )
        )
    ).all()
    have = {(sid, et) for sid, et in existing}

    payload = _app_reference_payload(pages, app.config or {})
    seen_types: set[str] = set()
    for page in pages:
        ot = page.get("object_type")
        if ot and ot not in seen_types:
            seen_types.add(ot)
            obj = (await session.execute(select(OntologyObject).where(OntologyObject.type_name == ot))).scalar_one_or_none()
            if obj is not None:
                ot_res = await get_resource_for_object(session, "ontology_object_type", obj.id)
                if ot_res is not None:
                    await _record_ref(session, app_resource=app_resource, source_resource=ot_res, edge_type="object_type_to_application", metadata={"object_type": ot}, have=have)
                ds_res = await get_resource_for_object(session, "dataset", obj.dataset_id)
                if ds_res is not None:
                    await _record_ref(session, app_resource=app_resource, source_resource=ds_res, edge_type="dataset_to_application", metadata={"via_object_type": ot}, have=have)

    for ds_id in _values_for_keys(payload, {"dataset_id", "dataset_ids"}):
        await _record_ref(session, app_resource=app_resource, source_resource=await _resource_by_object(session, "dataset", ds_id), edge_type="dataset_to_application", metadata={"dataset_id": str(ds_id)}, have=have)
    for query_id in _values_for_keys(payload, {"saved_query_id", "saved_query_ids", "query_id"}):
        await _record_ref(session, app_resource=app_resource, source_resource=await _resource_by_object(session, "saved_query", query_id), edge_type="saved_query_to_application", metadata={"saved_query_id": str(query_id)}, have=have)
    for dashboard_id in _values_for_keys(payload, {"dashboard_id", "dashboard_ids"}):
        await _record_ref(session, app_resource=app_resource, source_resource=await _resource_by_object(session, "dashboard", dashboard_id), edge_type="dashboard_to_application", metadata={"dashboard_id": str(dashboard_id)}, have=have)
    for action_id in _values_for_keys(payload, {"action_id", "action_ids"}):
        await _record_ref(session, app_resource=app_resource, source_resource=await _resource_by_object(session, "ontology_action", action_id), edge_type="action_to_application", metadata={"action_id": str(action_id)}, have=have)
    for action_name in _values_for_keys(payload, {"action", "action_name"}):
        action = (await session.execute(select(OntologyAction).where(OntologyAction.name == action_name))).scalar_one_or_none()
        if action is not None:
            await _record_ref(session, app_resource=app_resource, source_resource=await get_resource_for_object(session, "ontology_action", action.id), edge_type="action_to_application", metadata={"action_name": action_name}, have=have)
    for model_id in _values_for_keys(payload, {"model_id", "model_ids"}):
        await _record_ref(session, app_resource=app_resource, source_resource=await _resource_by_object(session, "model", model_id), edge_type="model_to_application", metadata={"model_id": str(model_id)}, have=have)
    for ai_run_id in _values_for_keys(payload, {"ai_run_id", "ai_draft_run_id"}):
        await record_lineage(session, source_resource_id=None, target_resource_id=app_resource.id, edge_type="ai_run_to_application", metadata={"ai_run_id": str(ai_run_id)})


async def _app_latest_published_version(session, app: Application) -> int | None:
    resource = await get_resource_for_object(session, "application", app.id)
    if resource is None:
        return None
    return (await session.execute(
        select(ResourceVersion.version_number)
        .where(ResourceVersion.resource_id == resource.id)
        .order_by(ResourceVersion.version_number.desc())
        .limit(1)
    )).scalar()


async def _widget_allowed(session, user, widget: dict, notices: list[dict]) -> bool:
    for dataset_id in _values_for_keys(widget, {"dataset_id", "dataset_ids"}):
        resource = await _resource_by_object(session, "dataset", dataset_id)
        if resource is not None:
            caps = await effective_resource_capabilities(session, user, resource)
            if not ({"view_data", "use_in_sql", "manage"} & caps):
                notices.append({"type": "widget_hidden", "reason": "missing_dataset_capability"})
                return False
    for query_id in _values_for_keys(widget, {"saved_query_id", "saved_query_ids", "query_id"}):
        resource = await _resource_by_object(session, "saved_query", query_id)
        if resource is not None:
            caps = await effective_resource_capabilities(session, user, resource)
            if not ({"view_metadata", "use_in_sql", "manage"} & caps):
                notices.append({"type": "widget_hidden", "reason": "missing_saved_query_capability"})
                return False
    for action_id in _values_for_keys(widget, {"action_id", "action_ids"}):
        resource = await _resource_by_object(session, "ontology_action", action_id)
        if resource is not None:
            caps = await effective_resource_capabilities(session, user, resource)
            if not ({"run", "writeback", "manage"} & caps):
                notices.append({"type": "widget_hidden", "reason": "missing_action_capability"})
                return False
    return True


async def _runtime_snapshot(session, user, app: Application, snapshot: dict, *, mode: str) -> AppRuntimeOut:
    roles = set(await get_user_roles(session, user.id))
    notices: list[dict] = []
    visible_pages: list[dict] = []
    for page in snapshot.get("pages", []) or []:
        required_roles = set(page.get("role_visibility") or [])
        if required_roles and not (required_roles & roles):
            notices.append({"type": "page_hidden", "reason": "role_visibility"})
            continue
        sanitized = {k: v for k, v in page.items() if k != "config"}
        config = dict(page.get("config") or {})
        widgets = []
        for widget in config.get("widgets") or []:
            if not isinstance(widget, dict):
                continue
            widget_roles = set(widget.get("role_visibility") or [])
            if widget_roles and not (widget_roles & roles):
                notices.append({"type": "widget_hidden", "reason": "role_visibility"})
                continue
            if not await _widget_allowed(session, user, widget, notices):
                continue
            widgets.append(widget)
        config["widgets"] = widgets
        sanitized["config"] = config
        visible_pages.append(sanitized)
    return AppRuntimeOut(
        id=str(app.id),
        name=snapshot.get("name", app.name),
        config=snapshot.get("config", {}),
        pages=visible_pages,
        published_at=app.published_at.isoformat() if app.published_at else snapshot.get("published_at"),
        published_version=snapshot.get("published_version") or await _app_latest_published_version(session, app),
        mode=mode,
        notices=notices,
    )


async def _app_snapshot(session, app: Application) -> dict:
    pages = await _page_snapshot(session, app)
    return {"name": app.name, "description": app.description, "config": app.config or {}, "pages": pages}


async def _register_app_version(session, app: Application, user_id: uuid.UUID, branch_name: str, kind: str) -> ResourceVersion | None:
    resource = await get_resource_for_object(session, "application", app.id)
    if resource is None:
        return None
    return await register_resource_version(
        session,
        resource=resource,
        created_by=user_id,
        branch_name=branch_name or "main",
        manifest={"kind": kind, "branch_name": branch_name or "main", "application": await _app_snapshot(session, app)},
    )


async def _latest_app_branch(session, app: Application, branch_name: str) -> dict | None:
    resource = await get_resource_for_object(session, "application", app.id)
    if resource is None:
        return None
    version = (await session.execute(
        select(ResourceVersion)
        .where(ResourceVersion.resource_id == resource.id, ResourceVersion.branch_name == branch_name)
        .order_by(ResourceVersion.version_number.desc())
        .limit(1)
    )).scalar_one_or_none()
    return ((version.manifest if version else None) or {}).get("application")


def _app_out_from_snapshot(app: Application, snapshot: dict) -> ApplicationOut:
    pages = [
        PageOut(
            id=str(p.get("id") or uuid.uuid4()),
            title=p["title"],
            page_type=p.get("page_type", "object_table"),
            object_type=p.get("object_type"),
            config=p.get("config") or {},
            role_visibility=p.get("role_visibility") or [],
            position=p.get("position") or 0,
        )
        for p in snapshot.get("pages", [])
    ]
    return ApplicationOut(
        id=str(app.id),
        name=snapshot.get("name", app.name),
        description=snapshot.get("description", app.description),
        owner_id=str(app.owner_id) if app.owner_id else None,
        status=app.status,
        config=snapshot.get("config") or {},
        pages=pages,
        published_at=app.published_at,
        published_version=(app.published_config or {}).get("published_version"),
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


@router.post("/{application_id}/publish", response_model=ApplicationOut)
async def publish_application(application_id: uuid.UUID, session: SessionDep, user: CurrentUserDep, branch_name: str = Query(default="main")) -> ApplicationOut:
    app = await _require_app_cap(session, user, application_id, "publish")
    pages = await _page_snapshot(session, app)
    published_at = datetime.utcnow()
    snapshot = {
        "name": app.name,
        "config": app.config or {},
        "pages": pages,
        "published_at": published_at.isoformat(),
        "references": _app_reference_payload(pages, app.config or {}),
    }
    app.status = "published"
    app.published_at = published_at

    resource = await get_resource_for_object(session, "application", app.id)
    if resource is not None:
        version = await register_resource_version(
            session, resource=resource, created_by=user.id, branch_name=branch_name,
            manifest={"kind": "application_publish", "branch_name": branch_name, **snapshot},
        )
        snapshot["published_version"] = version.version_number
    app.published_config = snapshot
    await _record_app_lineage(session, app, pages)
    await log_event(session, user=user, event_type="APPLICATION_PUBLISHED", resource_type="application", resource_id=str(app.id))
    await session.commit()
    return await _app_out(session, app)


# --------------------------------------------------------- version history

class AppVersionOut(BaseModel):
    id: str
    version_number: int
    created_at: datetime
    published_at: str | None = None


@router.get("/{application_id}/versions", response_model=list[AppVersionOut])
async def list_app_versions(application_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[AppVersionOut]:
    await _require_app_cap(session, user, application_id, "view_metadata")
    resource = await get_resource_for_object(session, "application", application_id)
    if resource is None:
        return []
    rows = (await session.execute(
        select(ResourceVersion).where(ResourceVersion.resource_id == resource.id).order_by(ResourceVersion.version_number.desc())
    )).scalars().all()
    return [
        AppVersionOut(
            id=str(v.id), version_number=v.version_number, created_at=v.created_at,
            published_at=(v.manifest or {}).get("published_at"),
        )
        for v in rows
    ]


@router.get("/{application_id}/versions/{version_id}")
async def get_app_version(application_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    await _require_app_cap(session, user, application_id, "view_metadata")
    v = await session.get(ResourceVersion, version_id)
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    resource = await get_resource_for_object(session, "application", application_id)
    if resource is None or v.resource_id != resource.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")
    return {"id": str(v.id), "version_number": v.version_number, "manifest": v.manifest or {}}


@router.get("/{application_id}/published", response_model=AppRuntimeOut)
async def get_published_application(application_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> AppRuntimeOut:
    app = await _require_app_cap(session, user, application_id, "view_metadata")
    if not app.published_config:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "application not published")
    return await _runtime_snapshot(session, user, app, app.published_config, mode="published")


@router.get("/{application_id}/preview", response_model=AppRuntimeOut)
async def preview_application(application_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> AppRuntimeOut:
    app = await _require_app_cap(session, user, application_id, "edit")
    pages = await _page_snapshot(session, app)
    return await _runtime_snapshot(
        session,
        user,
        app,
        {"name": app.name, "config": app.config or {}, "pages": pages},
        mode="preview",
    )


class AppLineageEdgeOut(BaseModel):
    source_resource_id: str | None
    source_name: str | None
    source_type: str | None
    edge_type: str
    metadata: dict = {}


@router.get("/{application_id}/lineage", response_model=list[AppLineageEdgeOut])
async def get_app_lineage(application_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[AppLineageEdgeOut]:
    await _require_app_cap(session, user, application_id, "view_metadata")
    resource = await get_resource_for_object(session, "application", application_id)
    if resource is None:
        return []
    edges = (await session.execute(
        select(LineageEdge).where(LineageEdge.target_resource_id == resource.id)
    )).scalars().all()
    out: list[AppLineageEdgeOut] = []
    for e in edges:
        src = await session.get(Resource, e.source_resource_id) if e.source_resource_id else None
        out.append(AppLineageEdgeOut(
            source_resource_id=str(e.source_resource_id) if e.source_resource_id else None,
            source_name=src.name if src else None,
            source_type=src.resource_type if src else None,
            edge_type=e.edge_type,
            metadata=e.edge_metadata or {},
        ))
    return out
