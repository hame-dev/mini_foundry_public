import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.ai import gateway
from app.audit.logger import log_event
from app.dashboards import service
from app.dashboards.ai_generate import AIDashboardError, generate_dashboard_layout
from app.dashboards.cache import get_cached_render, render_cache_key, set_cached_render
from app.dashboards.data_binding import (
    BindingResolutionError,
    binding_cache_context,
    resolve_binding,
)
from app.dashboards.models import Dashboard, DashboardComponent, DashboardPermission, SavedQuery, SavedQueryVersion
from app.dashboards.permissions import effective_dashboard_permission
from app.dashboards.validation import LayoutValidationError, validate_layout
from app.deps import AdminDep, CurrentUserDep, SessionDep
from app.execution.sql_validator import SqlValidationError, validate_sql
from app.permissions.enforcement import (
    PermissionDenied,
    bump_permission_version,
    get_permission_version,
    require_object_capability,
)
from app.platform.models import ResourceACL, ResourceVersion
from app.platform.service import get_resource_for_object, record_lineage, register_resource_version, upsert_resource

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


# ----- pydantic ----------------------------------------------------------


class DashboardSummary(BaseModel):
    id: str
    title: str
    description: str | None
    owner_id: str | None
    dashboard_kind: str = "contour"
    published_version: int = 0
    published_at: datetime | None = None
    draft_updated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ComponentOut(BaseModel):
    id: str
    component_type: str
    title: str | None
    position: dict
    config: dict
    data_binding: dict | None
    refresh: dict | None


class DashboardDetail(DashboardSummary):
    layout: dict
    components: list[ComponentOut]
    is_draft_view: bool = True
    pages: list | None = None
    variables_schema: list | None = None


class CreateDashboardIn(BaseModel):
    title: str
    description: str | None = None
    layout: dict | None = None
    dashboard_kind: str = "contour"
    workspace_parent_id: uuid.UUID | None = None


class UpdateDashboardIn(BaseModel):
    title: str | None = None
    description: str | None = None
    layout: dict
    dashboard_kind: str | None = None
    pages: list | None = None
    variables_schema: list | None = None
    branch_name: str = "main"


class RenderIn(BaseModel):
    filters: dict[str, Any] = {}


class ComponentRender(BaseModel):
    id: str
    status: str = "ok"
    columns: list[str] | None = None
    rows: list[dict] | None = None
    dataset_versions: list[dict] | None = None
    engine: str | None = None
    query_hash: str | None = None
    error: str | None = None
    cached: bool = False
    elapsed_ms: int = 0


class RenderOut(BaseModel):
    dashboard_id: str
    components: list[ComponentRender]
    elapsed_ms: int = 0


class SavedQueryOut(BaseModel):
    id: str
    name: str
    sql: str
    dataset_ids: list[str]
    owner_id: str | None
    created_at: datetime


class SavedQueryVersionOut(BaseModel):
    id: str
    saved_query_id: str
    version_number: int
    sql: str
    dataset_ids: list[str]
    created_by: str | None
    created_at: datetime


class SavedQueryIn(BaseModel):
    name: str
    sql: str
    dataset_ids: list[uuid.UUID] = []
    workspace_parent_id: uuid.UUID | None = None


# ----- helpers -----------------------------------------------------------


def _summary(d: Dashboard) -> DashboardSummary:
    return DashboardSummary(
        id=str(d.id),
        title=d.title,
        description=d.description,
        owner_id=str(d.owner_id) if d.owner_id else None,
        dashboard_kind=d.dashboard_kind or "contour",
        published_version=d.published_version or 0,
        published_at=d.published_at,
        draft_updated_at=d.draft_updated_at,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


def _component_out(c: DashboardComponent) -> ComponentOut:
    return ComponentOut(
        id=str(c.id),
        component_type=c.component_type,
        title=c.title,
        position=c.position,
        config=c.config,
        data_binding=c.data_binding,
        refresh=c.refresh,
    )


def _saved_query_out(q: SavedQuery) -> SavedQueryOut:
    return SavedQueryOut(
        id=str(q.id),
        name=q.name,
        sql=q.sql,
        dataset_ids=[str(x) for x in q.dataset_ids],
        owner_id=str(q.owner_id) if q.owner_id else None,
        created_at=q.created_at,
    )


def _saved_query_version_out(v: SavedQueryVersion) -> SavedQueryVersionOut:
    return SavedQueryVersionOut(
        id=str(v.id),
        saved_query_id=str(v.saved_query_id),
        version_number=v.version_number,
        sql=v.sql,
        dataset_ids=[str(x) for x in v.dataset_ids],
        created_by=str(v.created_by) if v.created_by else None,
        created_at=v.created_at,
    )


def _dashboard_caps_from_payload(payload: "GrantDashboardIn") -> list[str]:
    caps = []
    if payload.can_view:
        caps.append("view_metadata")
    if payload.can_edit:
        caps.extend(["edit", "view_metadata"])
    if payload.can_share:
        caps.append("grant")
    if payload.can_manage:
        caps.extend(["manage", "view_metadata", "edit", "grant", "publish"])
    return sorted(set(caps))


async def _create_saved_query_version(session: SessionDep, query: SavedQuery, user_id: uuid.UUID) -> SavedQueryVersion:
    max_version = (
        await session.execute(select(func.max(SavedQueryVersion.version_number)).where(SavedQueryVersion.saved_query_id == query.id))
    ).scalar_one_or_none()
    version = SavedQueryVersion(
        saved_query_id=query.id,
        version_number=int(max_version or 0) + 1,
        sql=query.sql,
        dataset_ids=list(query.dataset_ids or []),
        created_by=user_id,
    )
    session.add(version)
    await session.flush()
    return version


async def _record_saved_query_lineage(session: SessionDep, query: SavedQuery, version: SavedQueryVersion | None = None) -> None:
    query_resource = await get_resource_for_object(session, "saved_query", query.id)
    if query_resource is None:
        return
    for dataset_id in query.dataset_ids or []:
        dataset_resource = await get_resource_for_object(session, "dataset", dataset_id)
        if dataset_resource is None:
            continue
        await record_lineage(
            session,
            source_resource_id=dataset_resource.id,
            target_resource_id=query_resource.id,
            edge_type="dataset_to_saved_query",
            target_version_id=version.id if version else None,
            metadata={
                "saved_query_id": str(query.id),
                "saved_query_version": version.version_number if version else None,
                "branch_name": "main",
            },
        )


async def _record_dashboard_definition_lineage(session: SessionDep, dashboard: Dashboard) -> None:
    dashboard_resource = await get_resource_for_object(session, "dashboard", dashboard.id)
    if dashboard_resource is None:
        return
    for component in (dashboard.layout or {}).get("components", []) or []:
        binding = component.get("data_binding") or {}
        component_id = component.get("id")
        if binding.get("type") == "saved_query" and binding.get("id"):
            try:
                query_resource = await get_resource_for_object(session, "saved_query", uuid.UUID(str(binding["id"])))
            except ValueError:
                query_resource = None
            if query_resource is not None:
                await record_lineage(
                    session,
                    source_resource_id=query_resource.id,
                    target_resource_id=dashboard_resource.id,
                    edge_type="saved_query_to_dashboard",
                    metadata={"component_id": str(component_id), "branch_name": "main"},
                )
        dataset_id = binding.get("dataset_id")
        if dataset_id:
            try:
                dataset_resource = await get_resource_for_object(session, "dataset", uuid.UUID(str(dataset_id)))
            except ValueError:
                dataset_resource = None
            if dataset_resource is not None:
                await record_lineage(
                    session,
                    source_resource_id=dataset_resource.id,
                    target_resource_id=dashboard_resource.id,
                    edge_type="dataset_to_dashboard_definition",
                    metadata={"component_id": str(component_id), "branch_name": "main"},
                )


async def _dashboard_snapshot(session: SessionDep, d: Dashboard) -> dict:
    got = await service.get_dashboard_with_components(session, d.id)
    cmps = got[1] if got else []
    return DashboardDetail(
        **_summary(d).model_dump(),
        layout=d.layout,
        components=[_component_out(c) for c in cmps],
        is_draft_view=True,
        pages=d.pages,
        variables_schema=d.variables_schema,
    ).model_dump(mode="json")


async def _register_dashboard_version(session: SessionDep, d: Dashboard, user_id: uuid.UUID, branch_name: str, kind: str) -> None:
    resource = await get_resource_for_object(session, "dashboard", d.id)
    if resource is None:
        return
    await register_resource_version(
        session,
        resource=resource,
        created_by=user_id,
        branch_name=branch_name or "main",
        manifest={"kind": kind, "branch_name": branch_name or "main", "dashboard": await _dashboard_snapshot(session, d)},
    )


async def _latest_dashboard_branch_detail(session: SessionDep, d: Dashboard, branch_name: str) -> DashboardDetail | None:
    resource = await get_resource_for_object(session, "dashboard", d.id)
    if resource is None:
        return None
    version = (await session.execute(
        select(ResourceVersion)
        .where(ResourceVersion.resource_id == resource.id, ResourceVersion.branch_name == branch_name)
        .order_by(ResourceVersion.version_number.desc())
        .limit(1)
    )).scalar_one_or_none()
    payload = ((version.manifest if version else None) or {}).get("dashboard")
    return DashboardDetail(**payload) if payload else None
WIDGET_REGISTRY = [
    {"id": "object_table", "label": "Object table", "category": "Properties and links", "description": "Display object data in a tabular format with inline editing affordances."},
    {"id": "metric_card", "label": "Metric card", "category": "Visualize", "description": "Highlight a key metric or status."},
    {"id": "button_group", "label": "Button group", "category": "Writeback", "description": "Trigger actions, workflow events, or links."},
    {"id": "filter_list", "label": "Filter list", "category": "Filter", "description": "Filter objects or datasets by high-level facets."},
    {"id": "chart_xy", "label": "Chart: XY", "category": "Visualize", "description": "Render bar, line, or scatter charts."},
    {"id": "markdown", "label": "Notepad", "category": "Foundry apps", "description": "Add rich text and embedded analysis notes."},
    {"id": "data_table", "label": "Data table", "category": "All", "description": "Preview dataset or SQL rows."},
]


@router.get("/widgets")
async def list_widgets(user: CurrentUserDep) -> dict:  # noqa: ARG001
    categories = ["All", "Properties and links", "Visualize", "Filter", "Writeback", "Foundry apps", "Unused widgets"]
    return {"categories": categories, "widgets": WIDGET_REGISTRY}


@router.get("/saved-queries", response_model=list[SavedQueryOut])
async def list_saved_queries(session: SessionDep, user: CurrentUserDep) -> list[SavedQueryOut]:
    rows = await session.execute(
        select(SavedQuery).where(SavedQuery.owner_id == user.id).order_by(SavedQuery.created_at.desc())
    )
    return [_saved_query_out(q) for q in rows.scalars().all()]


@router.post("/saved-queries", response_model=SavedQueryOut)
async def create_saved_query(payload: SavedQueryIn, session: SessionDep, user: CurrentUserDep) -> SavedQueryOut:
    try:
        validate_sql(payload.sql)
    except SqlValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    for dataset_id in payload.dataset_ids:
        try:
            await require_object_capability(session, user, "dataset", dataset_id, "use_in_sql")
        except PermissionDenied as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    q = SavedQuery(name=payload.name, sql=payload.sql, dataset_ids=payload.dataset_ids, owner_id=user.id)
    session.add(q)
    await session.flush()
    version = await _create_saved_query_version(session, q, user.id)
    await upsert_resource(
        session,
        resource_type="saved_query",
        object_id=q.id,
        name=q.name,
        owner_user_id=user.id,
        metadata={"dataset_ids": [str(x) for x in q.dataset_ids]},
    )
    await _record_saved_query_lineage(session, q, version)
    from app.workspace.service import create_linked_item
    await create_linked_item(
        session,
        user_id=user.id,
        name=q.name,
        item_type="sql",
        resource_type="saved_query",
        resource_id=q.id,
        parent_id=payload.workspace_parent_id,
    )
    await log_event(
        session, user=user, event_type="SAVED_QUERY_EDITED",
        resource_type="saved_query", resource_id=str(q.id),
        input_summary={"action": "create", "name": q.name, "version": version.version_number},
    )
    await session.commit()
    return _saved_query_out(q)


@router.put("/saved-queries/{query_id}", response_model=SavedQueryOut)
async def update_saved_query(
    query_id: uuid.UUID, payload: SavedQueryIn, session: SessionDep, user: CurrentUserDep
) -> SavedQueryOut:
    q = await session.get(SavedQuery, query_id)
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "saved query not found")
    if q.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not the saved query owner")
    try:
        validate_sql(payload.sql)
    except SqlValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    for dataset_id in payload.dataset_ids:
        try:
            await require_object_capability(session, user, "dataset", dataset_id, "use_in_sql")
        except PermissionDenied as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    q.name = payload.name
    q.sql = payload.sql
    q.dataset_ids = payload.dataset_ids
    version = await _create_saved_query_version(session, q, user.id)
    await upsert_resource(
        session,
        resource_type="saved_query",
        object_id=q.id,
        name=q.name,
        owner_user_id=user.id,
        metadata={"dataset_ids": [str(x) for x in q.dataset_ids], "latest_version": version.version_number},
    )
    await _record_saved_query_lineage(session, q, version)
    await log_event(
        session, user=user, event_type="SAVED_QUERY_EDITED",
        resource_type="saved_query", resource_id=str(q.id),
        input_summary={"action": "update", "name": q.name, "version": version.version_number},
    )
    await session.commit()
    return _saved_query_out(q)


@router.delete("/saved-queries/{query_id}")
async def delete_saved_query(query_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    q = await session.get(SavedQuery, query_id)
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "saved query not found")
    if q.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not the saved query owner")
    await session.delete(q)
    await log_event(
        session, user=user, event_type="SAVED_QUERY_EDITED",
        resource_type="saved_query", resource_id=str(query_id),
        input_summary={"action": "delete"},
    )
    await session.commit()
    return {"ok": True}


@router.get("/saved-queries/{query_id}/versions", response_model=list[SavedQueryVersionOut])
async def list_saved_query_versions(query_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[SavedQueryVersionOut]:
    q = await session.get(SavedQuery, query_id)
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "saved query not found")
    if q.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not the saved query owner")
    rows = (
        await session.execute(
            select(SavedQueryVersion).where(SavedQueryVersion.saved_query_id == query_id).order_by(SavedQueryVersion.version_number.desc())
        )
    ).scalars().all()
    return [_saved_query_version_out(row) for row in rows]


# ----- CRUD --------------------------------------------------------------


@router.get("", response_model=list[DashboardSummary])
async def list_dashboards(session: SessionDep, user: CurrentUserDep) -> list[DashboardSummary]:
    rows = await service.list_visible_dashboards(session, user.id)
    return [_summary(r) for r in rows]


@router.post("", response_model=DashboardDetail)
async def create_dashboard(
    payload: CreateDashboardIn, session: SessionDep, user: CurrentUserDep
) -> DashboardDetail:
    layout = payload.layout or {"version": 1, "components": [], "filters": []}
    try:
        validate_layout(layout)
    except LayoutValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    kind = payload.dashboard_kind if payload.dashboard_kind in {"contour", "workshop", "quiver"} else "contour"
    d = Dashboard(title=payload.title, description=payload.description, layout=layout, owner_id=user.id, dashboard_kind=kind)
    d.draft_updated_at = datetime.utcnow()
    session.add(d)
    await session.flush()
    await upsert_resource(
        session,
        resource_type="dashboard",
        object_id=d.id,
        name=d.title,
        owner_user_id=user.id,
        metadata={"dashboard_kind": kind, "published_version": d.published_version},
    )

    session.add(
        DashboardPermission(
            dashboard_id=d.id, subject_type="user", subject_id=user.id,
            can_view=True, can_edit=True, can_share=True, can_manage=True,
        )
    )
    components = await service.replace_components_from_layout(session, d, layout)
    from app.workspace.service import create_linked_item
    await create_linked_item(
        session,
        user_id=user.id,
        name=d.title,
        item_type="dashboard",
        resource_type="dashboard",
        resource_id=d.id,
        parent_id=payload.workspace_parent_id,
    )
    await bump_permission_version(session)
    await log_event(
        session, user=user, event_type="DASHBOARD_EDITED",
        resource_type="dashboard", resource_id=str(d.id),
        input_summary={"action": "create", "title": d.title},
    )
    await session.commit()
    return DashboardDetail(
        **_summary(d).model_dump(),
        layout=d.layout,
        components=[_component_out(c) for c in components],
        is_draft_view=True,
    )


@router.get("/{dashboard_id}", response_model=DashboardDetail)
async def get_dashboard(
    dashboard_id: uuid.UUID, session: SessionDep, user: CurrentUserDep, branch_name: str | None = Query(default=None)
) -> DashboardDetail:
    got = await service.get_dashboard_with_components(session, dashboard_id)
    if got is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dashboard not found")
    d, cmps = got
    if not await service.can_view(session, user, d):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no view permission")
    if branch_name and branch_name != "main":
        branch_detail = await _latest_dashboard_branch_detail(session, d, branch_name)
        if branch_detail is not None:
            return branch_detail
    can_edit = await service.can_edit(session, user, d)
    visible_layout = d.layout if can_edit or not d.published_layout else d.published_layout
    visible_components = cmps
    if not can_edit and d.published_layout:
        visible_components = [
            DashboardComponent(
                id=uuid.UUID(c["id"]),
                dashboard_id=d.id,
                component_type=c["component_type"],
                title=c.get("title"),
                position=c["position"],
                config=c.get("config", {}),
                data_binding=c.get("data_binding"),
                refresh=c.get("refresh"),
            )
            for c in visible_layout.get("components", [])
        ]
    return DashboardDetail(
        **_summary(d).model_dump(),
        layout=visible_layout,
        components=[_component_out(c) for c in visible_components],
        is_draft_view=can_edit or not bool(d.published_layout),
        pages=d.pages,
        variables_schema=d.variables_schema,
    )


@router.put("/{dashboard_id}", response_model=DashboardDetail)
async def update_dashboard(
    dashboard_id: uuid.UUID,
    payload: UpdateDashboardIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> DashboardDetail:
    d = await session.get(Dashboard, dashboard_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dashboard not found")
    if not await service.can_edit(session, user, d):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no edit permission")
    try:
        validate_layout(payload.layout)
    except LayoutValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))

    if payload.title is not None:
        d.title = payload.title
    if payload.description is not None:
        d.description = payload.description
    if payload.dashboard_kind is not None:
        if payload.dashboard_kind not in {"contour", "workshop", "quiver"}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "dashboard_kind must be contour|workshop|quiver")
        d.dashboard_kind = payload.dashboard_kind
    d.layout = payload.layout
    if payload.pages is not None:
        d.pages = payload.pages
    if payload.variables_schema is not None:
        d.variables_schema = payload.variables_schema
    d.updated_at = datetime.utcnow()
    d.draft_updated_at = datetime.utcnow()
    components = await service.replace_components_from_layout(session, d, payload.layout)
    await upsert_resource(
        session,
        resource_type="dashboard",
        object_id=d.id,
        name=d.title,
        owner_user_id=d.owner_id,
        metadata={"dashboard_kind": d.dashboard_kind, "published_version": d.published_version},
    )
    await _register_dashboard_version(session, d, user.id, payload.branch_name, "dashboard_draft_saved")
    await _record_dashboard_definition_lineage(session, d)
    await log_event(
        session, user=user, event_type="DASHBOARD_EDITED",
        resource_type="dashboard", resource_id=str(d.id),
        input_summary={"action": "update", "component_count": len(components), "branch_name": payload.branch_name},
    )
    await session.commit()
    return DashboardDetail(
        **_summary(d).model_dump(),
        layout=d.layout,
        components=[_component_out(c) for c in components],
        is_draft_view=True,
    )


@router.post("/{dashboard_id}/publish", response_model=DashboardDetail)
async def publish_dashboard(
    dashboard_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
    branch_name: str = Query(default="main"),
) -> DashboardDetail:
    got = await service.get_dashboard_with_components(session, dashboard_id)
    if got is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dashboard not found")
    d, cmps = got
    if not await service.can_edit(session, user, d):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no edit permission")
    d.published_layout = d.layout
    d.published_version = int(d.published_version or 0) + 1
    d.published_at = datetime.utcnow()
    d.updated_at = datetime.utcnow()
    await upsert_resource(
        session,
        resource_type="dashboard",
        object_id=d.id,
        name=d.title,
        owner_user_id=d.owner_id,
        metadata={"dashboard_kind": d.dashboard_kind, "published_version": d.published_version},
    )
    await _register_dashboard_version(session, d, user.id, branch_name, "dashboard_published")
    await _record_dashboard_definition_lineage(session, d)
    await log_event(
        session, user=user, event_type="DASHBOARD_PUBLISHED",
        resource_type="dashboard", resource_id=str(d.id),
        input_summary={"version": d.published_version, "branch_name": branch_name},
    )
    await session.commit()
    return DashboardDetail(
        **_summary(d).model_dump(),
        layout=d.layout,
        components=[_component_out(c) for c in cmps],
        is_draft_view=True,
    )


@router.delete("/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: uuid.UUID, session: SessionDep, user: CurrentUserDep
) -> dict:
    d = await session.get(Dashboard, dashboard_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dashboard not found")
    if not await service.can_manage(session, user, d):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no manage permission")
    await session.delete(d)
    await log_event(
        session, user=user, event_type="DASHBOARD_EDITED",
        resource_type="dashboard", resource_id=str(dashboard_id),
        input_summary={"action": "delete"},
    )
    await session.commit()
    return {"ok": True}


# ----- render ------------------------------------------------------------


async def _render_one(
    session: SessionDep, user: CurrentUserDep,
    dashboard_id: uuid.UUID, component: DashboardComponent,
    filters: dict[str, Any], permission_version: int,
) -> ComponentRender:
    import time
    start = time.perf_counter()
    refresh = component.refresh or {}
    mode = refresh.get("mode", "cached")
    ttl = int(refresh.get("ttl_seconds", 300))
    cache_context = await binding_cache_context(session, component.data_binding)

    key = render_cache_key(
        user_id=user.id, dashboard_id=dashboard_id, component_id=component.id,
        binding=component.data_binding, filters=filters,
        permission_version=permission_version,
        cache_context=cache_context,
    )

    if mode == "cached":
        cached = await get_cached_render(key)
        if cached is not None:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return ComponentRender(id=str(component.id), status="cached", cached=True, elapsed_ms=elapsed_ms, **cached)

    try:
        result = await resolve_binding(session, user, component.data_binding, filters)
    except PermissionDenied as e:
        return ComponentRender(id=str(component.id), status="error", error=f"permission_denied: {e}", elapsed_ms=int((time.perf_counter() - start) * 1000))
    except SqlValidationError as e:
        return ComponentRender(id=str(component.id), status="error", error=f"sql_invalid: {e}", elapsed_ms=int((time.perf_counter() - start) * 1000))
    except BindingResolutionError as e:
        return ComponentRender(id=str(component.id), status="error", error=f"binding_invalid: {e}. Check the widget data binding and supported Contour fields.", elapsed_ms=int((time.perf_counter() - start) * 1000))
    except Exception as e:  # noqa: BLE001
        return ComponentRender(id=str(component.id), status="error", error=f"render_error: {e}", elapsed_ms=int((time.perf_counter() - start) * 1000))

    payload = {
        "columns": result["columns"],
        "rows": result["rows"],
        "dataset_versions": result.get("dataset_versions") or cache_context.get("dataset_versions", []),
        "engine": result.get("engine") or cache_context.get("engine"),
        "query_hash": result.get("query_hash"),
    }
    if mode != "live":
        await set_cached_render(key, payload, ttl_seconds=ttl)
    return ComponentRender(id=str(component.id), status="ok", cached=False, elapsed_ms=int((time.perf_counter() - start) * 1000), **payload)


@router.post("/{dashboard_id}/render", response_model=RenderOut)
async def render_dashboard(
    dashboard_id: uuid.UUID, payload: RenderIn,
    session: SessionDep, user: CurrentUserDep,
) -> RenderOut:
    import time
    start = time.perf_counter()
    got = await service.get_dashboard_with_components(session, dashboard_id)
    if got is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dashboard not found")
    d, cmps = got
    if not await service.can_view(session, user, d):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no view permission")

    effective = await effective_dashboard_permission(session, user.id, dashboard_id)
    render_components = cmps
    if not effective.can_edit and d.published_layout:
        render_components = [
            DashboardComponent(
                id=uuid.UUID(comp["id"]),
                dashboard_id=d.id,
                component_type=comp["component_type"],
                title=comp.get("title"),
                position=comp.get("position") or {},
                config=comp.get("config") or {},
                data_binding=comp.get("data_binding"),
                refresh=comp.get("refresh"),
            )
            for comp in d.published_layout.get("components", [])
        ]

    version = await get_permission_version(session)
    results: list[ComponentRender] = []
    for c in render_components:
        component_result = await _render_one(session, user, dashboard_id, c, payload.filters, version)
        results.append(component_result)
        dashboard_resource = await get_resource_for_object(session, "dashboard", dashboard_id)
        if dashboard_resource and component_result.dataset_versions:
            for dataset_version in component_result.dataset_versions:
                dataset_id = dataset_version.get("dataset_id")
                if not dataset_id:
                    continue
                dataset_resource = await get_resource_for_object(session, "dataset", uuid.UUID(dataset_id))
                if dataset_resource:
                    column_mappings = [
                        {"source_column": col, "target_column": col, "transform": "dashboard_binding", "confidence": 0.8}
                        for col in (component_result.columns or [])
                    ]
                    await record_lineage(
                        session,
                        source_resource_id=dataset_resource.id,
                        source_version_id=uuid.UUID(dataset_version["dataset_version_id"]) if dataset_version.get("dataset_version_id") else None,
                        target_resource_id=dashboard_resource.id,
                        edge_type="dataset_to_dashboard_widget",
                        metadata={
                            "component_id": str(c.id),
                            "dashboard_id": str(dashboard_id),
                            "query_hash": component_result.query_hash,
                            "branch_name": dataset_version.get("branch_name", "main"),
                            "column_mappings": column_mappings,
                        },
                    )

    await log_event(
        session, user=user, event_type="DASHBOARD_VIEWED",
        resource_type="dashboard", resource_id=str(dashboard_id),
        output_summary={"component_count": len(results)},
    )
    await session.commit()
    return RenderOut(dashboard_id=str(dashboard_id), components=results, elapsed_ms=int((time.perf_counter() - start) * 1000))


@router.post("/{dashboard_id}/components/{component_id}/render", response_model=ComponentRender)
async def render_component(
    dashboard_id: uuid.UUID, component_id: uuid.UUID,
    payload: RenderIn,
    session: SessionDep, user: CurrentUserDep,
) -> ComponentRender:
    d = await session.get(Dashboard, dashboard_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dashboard not found")
    if not await service.can_view(session, user, d):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no view permission")
    c = await session.get(DashboardComponent, component_id)
    if c is None or c.dashboard_id != dashboard_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "component not found")
    version = await get_permission_version(session)
    result = await _render_one(session, user, dashboard_id, c, payload.filters, version)
    await session.commit()
    return result


# ----- AI generation -----------------------------------------------------


class AiGenerateIn(BaseModel):
    prompt: str
    provider: str = "ollama"
    model: str | None = None
    dataset_ids: list[uuid.UUID] | None = None


class AiGenerateOut(BaseModel):
    title: str
    description: str | None
    layout: dict
    provider: str
    model: str


@router.post("/ai-generate", response_model=AiGenerateOut)
async def ai_generate(
    payload: AiGenerateIn, session: SessionDep, user: CurrentUserDep
) -> AiGenerateOut:
    model = payload.model or gateway.default_model_for(payload.provider)
    try:
        result = await generate_dashboard_layout(
            session=session,
            user=user,
            prompt=payload.prompt,
            provider=payload.provider,
            model=model,
            dataset_ids=payload.dataset_ids,
        )
    except gateway.AIPolicyError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    except AIDashboardError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    except LayoutValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"AI returned invalid layout: {e}")

    await log_event(
        session, user=user, event_type="AI_PROVIDER_USED",
        resource_type="dashboard_ai_generate", provider=payload.provider,
        input_summary={"prompt": payload.prompt, "model": model},
        output_summary={"title": result["title"], "component_count": len(result["layout"].get("components", []))},
    )
    await session.commit()
    return AiGenerateOut(
        title=result["title"],
        description=result["description"],
        layout=result["layout"],
        provider=payload.provider,
        model=model,
    )


# ----- permissions admin -------------------------------------------------


class GrantDashboardIn(BaseModel):
    subject_type: str  # "user" | "role" | "everyone"
    subject_id: uuid.UUID | None = None
    can_view: bool = False
    can_edit: bool = False
    can_share: bool = False
    can_manage: bool = False


@router.post("/{dashboard_id}/permissions")
async def grant_dashboard_perm(
    dashboard_id: uuid.UUID,
    payload: GrantDashboardIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    d = await session.get(Dashboard, dashboard_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dashboard not found")
    # Manage rights required: owner or any user-level can_manage
    if d.owner_id != user.id:
        eff = await effective_dashboard_permission(session, user.id, dashboard_id)
        if not (eff.can_manage or eff.can_share):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "no share/manage permission")
    if payload.subject_type not in ("user", "role", "everyone"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "subject_type must be user|role|everyone")
    if payload.subject_type != "everyone" and payload.subject_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "subject_id required")

    existing_q = await session.execute(
        select(DashboardPermission).where(
            DashboardPermission.dashboard_id == dashboard_id,
            DashboardPermission.subject_type == payload.subject_type,
            DashboardPermission.subject_id == payload.subject_id,
        )
    )
    row = existing_q.scalar_one_or_none()
    fields = payload.model_dump(exclude={"subject_type", "subject_id"})
    if row is None:
        session.add(DashboardPermission(
            dashboard_id=dashboard_id,
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            **fields,
        ))
    else:
        for k, v in fields.items():
            setattr(row, k, v)
    resource = await get_resource_for_object(session, "dashboard", dashboard_id)
    if resource is not None:
        subject_type = "all_users" if payload.subject_type == "everyone" else payload.subject_type
        acl = (
            await session.execute(
                select(ResourceACL).where(
                    ResourceACL.resource_id == resource.id,
                    ResourceACL.subject_type == subject_type,
                    ResourceACL.subject_id == payload.subject_id,
                )
            )
        ).scalar_one_or_none()
        caps = _dashboard_caps_from_payload(payload)
        if acl is None:
            session.add(
                ResourceACL(
                    resource_id=resource.id,
                    subject_type=subject_type,
                    subject_id=payload.subject_id,
                    capabilities=caps,
                )
            )
        else:
            acl.capabilities = caps
    version = await bump_permission_version(session)
    await log_event(
        session, user=user, event_type="PERMISSION_CHANGED",
        resource_type="dashboard", resource_id=str(dashboard_id),
        input_summary={"subject_type": payload.subject_type, "subject_id": str(payload.subject_id), **fields},
    )
    await session.commit()
    return {"ok": True, "permission_version": version}


@router.delete("/{dashboard_id}/permissions")
async def revoke_dashboard_perm(
    dashboard_id: uuid.UUID,
    subject_type: str,
    session: SessionDep, user: CurrentUserDep,
    subject_id: uuid.UUID | None = None,
) -> dict:
    d = await session.get(Dashboard, dashboard_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dashboard not found")
    if d.owner_id != user.id:
        eff = await effective_dashboard_permission(session, user.id, dashboard_id)
        if not (eff.can_manage or eff.can_share):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "no share/manage permission")
    row_q = await session.execute(
        select(DashboardPermission).where(
            DashboardPermission.dashboard_id == dashboard_id,
            DashboardPermission.subject_type == subject_type,
            DashboardPermission.subject_id == subject_id,
        )
    )
    row = row_q.scalar_one_or_none()
    if row is not None:
        await session.delete(row)
    resource = await get_resource_for_object(session, "dashboard", dashboard_id)
    if resource is not None:
        acl_subject_type = "all_users" if subject_type == "everyone" else subject_type
        acl_q = await session.execute(
            select(ResourceACL).where(
                ResourceACL.resource_id == resource.id,
                ResourceACL.subject_type == acl_subject_type,
                ResourceACL.subject_id == subject_id,
            )
        )
        acl = acl_q.scalar_one_or_none()
        if acl is not None:
            await session.delete(acl)
    version = await bump_permission_version(session)
    await log_event(
        session, user=user, event_type="PERMISSION_CHANGED",
        resource_type="dashboard", resource_id=str(dashboard_id),
        input_summary={"action": "revoke", "subject_type": subject_type, "subject_id": str(subject_id)},
    )
    await session.commit()
    return {"ok": True, "permission_version": version}
