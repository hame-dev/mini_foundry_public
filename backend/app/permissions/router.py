import uuid
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.audit.logger import log_event
from app.data.models import Dataset
from app.deps import AdminDep, SessionDep
from app.permissions.enforcement import bump_permission_version
from app.platform.models import ResourceACL
from app.platform.service import get_resource_for_object

router = APIRouter(prefix="/admin/permissions", tags=["permissions"])


class GrantIn(BaseModel):
    dataset_id: uuid.UUID
    subject_type: str  # "user" | "role"
    subject_id: uuid.UUID
    can_view_metadata: bool = False
    can_view_data: bool = False
    can_use_in_sql: bool = False
    can_use_in_python: bool = False
    can_use_with_ai: bool = False
    can_export: bool = False
    can_edit: bool = False
    can_manage: bool = False


@router.post("/grant")
async def grant(payload: GrantIn, session: SessionDep, admin: AdminDep) -> dict:
    ds = await session.get(Dataset, payload.dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    if payload.subject_type not in ("user", "role"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "subject_type must be 'user' or 'role'")

    fields = payload.model_dump(exclude={"dataset_id", "subject_type", "subject_id"})
    resource = await get_resource_for_object(session, "dataset", payload.dataset_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset resource not found")
    caps = []
    mapping = {
        "can_view_metadata": "view_metadata",
        "can_view_data": "view_data",
        "can_use_in_sql": "use_in_sql",
        "can_use_in_python": "use_in_python",
        "can_use_with_ai": "use_with_ai",
        "can_export": "export",
        "can_edit": "edit",
        "can_manage": "manage",
    }
    for field, cap in mapping.items():
        if fields.get(field):
            caps.append(cap)
    acl = (
        await session.execute(
            select(ResourceACL).where(
                ResourceACL.resource_id == resource.id,
                ResourceACL.subject_type == payload.subject_type,
                ResourceACL.subject_id == payload.subject_id,
            )
        )
    ).scalar_one_or_none()
    if acl is None:
        session.add(ResourceACL(resource_id=resource.id, subject_type=payload.subject_type, subject_id=payload.subject_id, capabilities=caps))
    else:
        acl.capabilities = caps

    version = await bump_permission_version(session)
    await log_event(
        session,
        user=admin,
        event_type="PERMISSION_CHANGED",
        resource_type="dataset",
        resource_id=str(payload.dataset_id),
        input_summary={"subject_type": payload.subject_type, "subject_id": str(payload.subject_id), **fields},
    )
    await session.commit()
    return {"ok": True, "permission_version": version}


@router.delete("/revoke")
async def revoke(
    dataset_id: uuid.UUID,
    subject_type: str,
    subject_id: uuid.UUID,
    session: SessionDep,
    admin: AdminDep,
) -> dict:
    resource = await get_resource_for_object(session, "dataset", dataset_id)
    if resource is not None:
        acl = (
            await session.execute(
                select(ResourceACL).where(
                    ResourceACL.resource_id == resource.id,
                    ResourceACL.subject_type == subject_type,
                    ResourceACL.subject_id == subject_id,
                )
            )
        ).scalar_one_or_none()
        if acl is not None:
            await session.delete(acl)
    version = await bump_permission_version(session)
    await log_event(
        session,
        user=admin,
        event_type="PERMISSION_CHANGED",
        resource_type="dataset",
        resource_id=str(dataset_id),
        input_summary={"action": "revoke", "subject_type": subject_type, "subject_id": str(subject_id)},
    )
    await session.commit()
    return {"ok": True, "permission_version": version}
