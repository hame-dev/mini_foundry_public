import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.audit.logger import log_event
from app.code_repo.models import CodeRepository
from app.dashboards.models import Dashboard, DashboardPermission, SavedQuery
from app.deps import CurrentUserDep, SessionDep
from app.ml.models import MLModel
from app.notebooks.models import Notebook
from app.pipelines.models import Pipeline
from app.workspace.models import WORKSPACE_ITEM_TYPES, WorkspaceItem, WorkspacePermission
from app.workspace.service import create_linked_item, effective_permission, ensure_root


router = APIRouter(prefix="/workspace", tags=["workspace"])


class WorkspaceItemOut(BaseModel):
    id: str
    name: str
    item_type: str
    parent_id: str | None
    resource_type: str | None
    resource_id: str | None
    owner_id: str | None
    href: str | None
    created_at: datetime
    updated_at: datetime


class WorkspacePermissionOut(BaseModel):
    id: str
    item_id: str
    subject_type: str
    subject_id: str | None
    can_view: bool
    can_edit: bool
    can_run: bool
    can_share: bool
    can_manage: bool


class CreateFolderIn(BaseModel):
    name: str
    parent_id: uuid.UUID | None = None


class CreateItemIn(BaseModel):
    name: str
    item_type: str
    parent_id: uuid.UUID | None = None
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None


class UpdateItemIn(BaseModel):
    name: str | None = None


class MoveItemIn(BaseModel):
    parent_id: uuid.UUID | None = None


class GrantWorkspaceIn(BaseModel):
    subject_type: str
    subject_id: uuid.UUID | None = None
    can_view: bool = False
    can_edit: bool = False
    can_run: bool = False
    can_share: bool = False
    can_manage: bool = False


def _href(item: WorkspaceItem) -> str | None:
    if item.item_type == "folder":
        return f"/workspace?folder={item.id}"
    if not item.resource_id:
        return None
    rid = str(item.resource_id)
    if item.item_type == "sql":
        return f"/sql?query={rid}"
    if item.item_type == "dashboard":
        return f"/dashboards/{rid}"
    if item.item_type == "notebook":
        return f"/notebooks/{rid}"
    if item.item_type == "code_repository":
        return f"/code-repo/{rid}"
    if item.item_type == "pipeline":
        return f"/pipelines/{rid}"
    if item.item_type == "model":
        return f"/models?model={rid}"
    if item.item_type == "dataset_link":
        return f"/catalog/{rid}"
    if item.item_type == "ontology":
        return "/admin/ontology"
    return None


def _item_out(i: WorkspaceItem) -> WorkspaceItemOut:
    return WorkspaceItemOut(
        id=str(i.id),
        name=i.name,
        item_type=i.item_type,
        parent_id=str(i.parent_id) if i.parent_id else None,
        resource_type=i.resource_type,
        resource_id=str(i.resource_id) if i.resource_id else None,
        owner_id=str(i.owner_id) if i.owner_id else None,
        href=_href(i),
        created_at=i.created_at,
        updated_at=i.updated_at,
    )


def _perm_out(p: WorkspacePermission) -> WorkspacePermissionOut:
    return WorkspacePermissionOut(
        id=str(p.id),
        item_id=str(p.item_id),
        subject_type=p.subject_type,
        subject_id=str(p.subject_id) if p.subject_id else None,
        can_view=p.can_view,
        can_edit=p.can_edit,
        can_run=p.can_run,
        can_share=p.can_share,
        can_manage=p.can_manage,
    )


async def _visible(session, user, item: WorkspaceItem) -> bool:
    return (await effective_permission(session, user.id, item)).can_view


async def _can_manage(session, user, item: WorkspaceItem) -> bool:
    return (await effective_permission(session, user.id, item)).can_manage


async def repair_workspace(session, user_id: uuid.UUID) -> None:
    await ensure_root(session, user_id)
    specs = [
        ("dashboard", "dashboard", Dashboard, Dashboard.title),
        ("notebook", "notebook", Notebook, Notebook.title),
        ("code_repository", "code_repository", CodeRepository, CodeRepository.name),
        ("pipeline", "pipeline", Pipeline, Pipeline.name),
        ("model", "model", MLModel, MLModel.name),
        ("sql", "saved_query", SavedQuery, SavedQuery.name),
    ]
    for item_type, resource_type, model, name_col in specs:
        try:
            rows = await session.execute(select(model).where(model.owner_id == user_id))
        except Exception:
            # Keep Compass usable even if a newer optional resource table has
            # not been migrated yet. The owning endpoint will surface the
            # precise migration issue when opened directly.
            continue
        for r in rows.scalars().all():
            exists = await session.execute(
                select(WorkspaceItem.id).where(
                    WorkspaceItem.resource_type == resource_type,
                    WorkspaceItem.resource_id == r.id,
                )
            )
            if exists.scalar_one_or_none() is None:
                await create_linked_item(
                    session,
                    user_id=user_id,
                    name=getattr(r, name_col.key),
                    item_type=item_type,
                    resource_type=resource_type,
                    resource_id=r.id,
                )


@router.get("/items", response_model=list[WorkspaceItemOut])
async def list_items(
    session: SessionDep,
    user: CurrentUserDep,
    parent_id: uuid.UUID | None = None,
    q: str | None = None,
) -> list[WorkspaceItemOut]:
    stmt = select(WorkspaceItem).order_by(WorkspaceItem.item_type, WorkspaceItem.name)
    if q:
        stmt = stmt.where(WorkspaceItem.name.ilike(f"%{q}%"))
    elif parent_id:
        stmt = stmt.where(WorkspaceItem.parent_id == parent_id)
    else:
        stmt = stmt.where(WorkspaceItem.parent_id.is_(None))
    rows = (await session.execute(stmt)).scalars().all()
    visible = [i for i in rows if await _visible(session, user, i)]
    return [_item_out(i) for i in visible]


@router.get("/roots", response_model=list[WorkspaceItemOut])
async def list_roots(session: SessionDep, user: CurrentUserDep) -> list[WorkspaceItemOut]:
    stmt = (
        select(WorkspaceItem)
        .where(WorkspaceItem.parent_id.is_(None), WorkspaceItem.item_type == "folder")
        .order_by(WorkspaceItem.name)
    )
    rows = (await session.execute(stmt)).scalars().all()
    visible = [i for i in rows if await _visible(session, user, i)]
    return [_item_out(i) for i in visible]


@router.post("/repair")
async def repair_workspace_index(session: SessionDep, user: CurrentUserDep) -> dict:
    await repair_workspace(session, user.id)
    await session.commit()
    return {"ok": True}


@router.post("/folders", response_model=WorkspaceItemOut)
async def create_folder(payload: CreateFolderIn, session: SessionDep, user: CurrentUserDep) -> WorkspaceItemOut:
    parent = await session.get(WorkspaceItem, payload.parent_id) if payload.parent_id else None
    if parent and not (await effective_permission(session, user.id, parent)).can_edit:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no edit permission on parent")
    item = await create_linked_item(
        session,
        user_id=user.id,
        name=payload.name,
        item_type="folder",
        resource_type=None,
        resource_id=None,
        parent_id=payload.parent_id,
    )
    await log_event(session, user=user, event_type="WORKSPACE_EDITED", resource_type="workspace_item", resource_id=str(item.id), input_summary={"action": "create_folder"})
    await session.commit()
    return _item_out(item)


@router.post("/items", response_model=WorkspaceItemOut)
async def create_item(payload: CreateItemIn, session: SessionDep, user: CurrentUserDep) -> WorkspaceItemOut:
    if payload.item_type not in WORKSPACE_ITEM_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown workspace item type")
    item = await create_linked_item(
        session,
        user_id=user.id,
        name=payload.name,
        item_type=payload.item_type,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        parent_id=payload.parent_id,
    )
    await session.commit()
    return _item_out(item)


@router.patch("/items/{item_id}", response_model=WorkspaceItemOut)
async def update_item(item_id: uuid.UUID, payload: UpdateItemIn, session: SessionDep, user: CurrentUserDep) -> WorkspaceItemOut:
    item = await session.get(WorkspaceItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace item not found")
    if not await _can_manage(session, user, item):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no manage permission")
    if payload.name is not None:
        item.name = payload.name
    item.updated_at = datetime.utcnow()
    await session.commit()
    return _item_out(item)


@router.post("/items/{item_id}/move", response_model=WorkspaceItemOut)
async def move_item(item_id: uuid.UUID, payload: MoveItemIn, session: SessionDep, user: CurrentUserDep) -> WorkspaceItemOut:
    item = await session.get(WorkspaceItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace item not found")
    if not await _can_manage(session, user, item):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no manage permission")
    item.parent_id = payload.parent_id
    item.updated_at = datetime.utcnow()
    await session.commit()
    return _item_out(item)


@router.delete("/items/{item_id}")
async def delete_item(item_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    item = await session.get(WorkspaceItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace item not found")
    if not await _can_manage(session, user, item):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no manage permission")
    await session.delete(item)
    await session.commit()
    return {"ok": True}


@router.get("/items/{item_id}/permissions", response_model=list[WorkspacePermissionOut])
async def list_permissions(item_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[WorkspacePermissionOut]:
    item = await session.get(WorkspaceItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace item not found")
    if not await _can_manage(session, user, item):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no manage permission")
    rows = await session.execute(select(WorkspacePermission).where(WorkspacePermission.item_id == item_id))
    return [_perm_out(p) for p in rows.scalars().all()]


@router.post("/items/{item_id}/permissions", response_model=WorkspacePermissionOut)
async def grant_permission(
    item_id: uuid.UUID, payload: GrantWorkspaceIn, session: SessionDep, user: CurrentUserDep
) -> WorkspacePermissionOut:
    item = await session.get(WorkspaceItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace item not found")
    if not await _can_manage(session, user, item):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no manage permission")
    if payload.subject_type not in ("user", "role", "everyone"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "subject_type must be user|role|everyone")
    subject_id = None if payload.subject_type == "everyone" else payload.subject_id
    if payload.subject_type != "everyone" and subject_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "subject_id required")
    fields = payload.model_dump(exclude={"subject_type", "subject_id"})
    existing = await session.execute(
        select(WorkspacePermission).where(
            WorkspacePermission.item_id == item_id,
            WorkspacePermission.subject_type == payload.subject_type,
            WorkspacePermission.subject_id == subject_id,
        )
    )
    p = existing.scalar_one_or_none()
    if p is None:
        p = WorkspacePermission(
            item_id=item_id,
            subject_type=payload.subject_type,
            subject_id=subject_id,
            **fields,
        )
        session.add(p)
    else:
        for key, value in fields.items():
            setattr(p, key, value)

    if item.resource_type == "dashboard" and item.resource_id is not None:
        dash_existing = await session.execute(
            select(DashboardPermission).where(
                DashboardPermission.dashboard_id == item.resource_id,
                DashboardPermission.subject_type == payload.subject_type,
                DashboardPermission.subject_id == subject_id,
            )
        )
        dash_perm = dash_existing.scalar_one_or_none()
        dash_fields = {
            "can_view": fields["can_view"],
            "can_edit": fields["can_edit"],
            "can_share": fields["can_share"],
            "can_manage": fields["can_manage"],
        }
        if dash_perm is None:
            session.add(DashboardPermission(
                dashboard_id=item.resource_id,
                subject_type=payload.subject_type,
                subject_id=subject_id,
                **dash_fields,
            ))
        else:
            for key, value in dash_fields.items():
                setattr(dash_perm, key, value)

    await session.flush()
    await session.commit()
    return _perm_out(p)


@router.delete("/items/{item_id}/permissions")
async def revoke_permission(
    item_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
    subject_type: str,
    subject_id: uuid.UUID | None = None,
) -> dict:
    item = await session.get(WorkspaceItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace item not found")
    if not await _can_manage(session, user, item):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no manage permission")
    rows = await session.execute(
        select(WorkspacePermission).where(
            WorkspacePermission.item_id == item_id,
            WorkspacePermission.subject_type == subject_type,
            WorkspacePermission.subject_id == subject_id,
        )
    )
    p = rows.scalar_one_or_none()
    if p:
        await session.delete(p)
    await session.commit()
    return {"ok": True}
