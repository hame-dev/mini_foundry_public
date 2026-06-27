"""Admin governance CRUD: roles, capabilities, row policies, column masks, secrets.

All endpoints are admin-guarded. Mutations bump the permission version (so
enforcement caches invalidate) and write an audit event, mirroring the pattern in
app/permissions/router.py. Secret values are never returned through the API.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.audit.logger import log_event
from app.auth.models import Role, UserRole
from app.auth.service import get_or_create_role
from app.data.models import Dataset, DatasetColumn
from app.deps import AdminDep, SessionDep
from app.permissions.enforcement import bump_permission_version
from app.permissions.models import ColumnPermission, RowPolicy, Secret
from app.permissions import secrets as secrets_service
from app.permissions.row_policy import RowPolicyDslError, compile_policy_dsl, validate_policy_references
from app.platform.models import Resource, ResourceACL
from app.platform.service import CANONICAL_CAPABILITIES

router = APIRouter(prefix="/governance", tags=["governance-admin"])

MASK_TYPES = {"hidden", "null", "hash", "partial", "none"}
SUBJECT_TYPES = {"user", "role", "group", "all_users"}

CAPABILITY_DESCRIPTIONS = {
    "view_metadata": "See the resource exists and its metadata",
    "view_data": "Read the underlying data / rows",
    "use_in_sql": "Reference the resource in governed SQL",
    "use_in_python": "Use the resource in sandboxed Python",
    "use_with_ai": "Use the resource in AI prompts / drafts",
    "run": "Execute the resource (pipeline, action, notebook, model)",
    "edit": "Modify the resource definition",
    "manage": "Full control including permissions and deletion",
    "export": "Export data out of the platform",
    "grant": "Grant access to other principals",
    "publish": "Publish a stable/published version",
    "writeback": "Write back to external systems via actions",
}


# ------------------------------------------------------------------- roles

class RoleIn(BaseModel):
    name: str


class RoleOut(BaseModel):
    id: str
    name: str
    member_count: int = 0


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(session: SessionDep, _: AdminDep) -> list[RoleOut]:
    counts = dict(
        (await session.execute(select(UserRole.role_id, func.count()).group_by(UserRole.role_id))).all()
    )
    roles = (await session.execute(select(Role).order_by(Role.name))).scalars().all()
    return [RoleOut(id=str(r.id), name=r.name, member_count=int(counts.get(r.id, 0))) for r in roles]


@router.post("/roles", response_model=RoleOut)
async def create_role(payload: RoleIn, session: SessionDep, admin: AdminDep) -> RoleOut:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role name required")
    role = await get_or_create_role(session, name)
    await log_event(session, user=admin, event_type="PERMISSION_CHANGED", resource_type="role",
                    resource_id=str(role.id), input_summary={"action": "create_role", "name": name})
    await session.commit()
    return RoleOut(id=str(role.id), name=role.name, member_count=0)


@router.delete("/roles/{role_id}")
async def delete_role(role_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "role not found")
    if role.name == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot delete the built-in admin role")
    await session.delete(role)
    await bump_permission_version(session)
    await log_event(session, user=admin, event_type="PERMISSION_CHANGED", resource_type="role",
                    resource_id=str(role_id), input_summary={"action": "delete_role", "name": role.name})
    await session.commit()
    return {"ok": True}


# ------------------------------------------------------------- capabilities

class CapabilityOut(BaseModel):
    name: str
    description: str


class CapabilityGrantOut(BaseModel):
    resource_id: str
    resource_type: str
    resource_name: str
    subject_type: str
    subject_id: str | None
    capabilities: list[str]


@router.get("/capabilities", response_model=list[CapabilityOut])
async def list_capabilities(_: AdminDep) -> list[CapabilityOut]:
    return [
        CapabilityOut(name=c, description=CAPABILITY_DESCRIPTIONS.get(c, ""))
        for c in sorted(CANONICAL_CAPABILITIES)
    ]


@router.get("/capabilities/grants", response_model=list[CapabilityGrantOut])
async def list_capability_grants(session: SessionDep, _: AdminDep, limit: int = Query(200, le=1000)) -> list[CapabilityGrantOut]:
    rows = (
        await session.execute(
            select(ResourceACL, Resource)
            .join(Resource, Resource.id == ResourceACL.resource_id)
            .order_by(Resource.name)
            .limit(limit)
        )
    ).all()
    return [
        CapabilityGrantOut(
            resource_id=str(res.id),
            resource_type=res.resource_type,
            resource_name=res.name,
            subject_type=acl.subject_type,
            subject_id=str(acl.subject_id) if acl.subject_id else None,
            capabilities=list(acl.capabilities or []),
        )
        for acl, res in rows
    ]


# ------------------------------------------------------------- row policies

class RowPolicyIn(BaseModel):
    dataset_id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID
    condition_json: dict


class RowPolicyOut(BaseModel):
    id: str
    dataset_id: str
    subject_type: str
    subject_id: str | None
    sql_condition: str
    condition_json: dict | None


def _row_policy_out(p: RowPolicy) -> RowPolicyOut:
    return RowPolicyOut(
        id=str(p.id), dataset_id=str(p.dataset_id), subject_type=p.subject_type,
        subject_id=str(p.subject_id) if p.subject_id else None,
        sql_condition=p.sql_condition, condition_json=p.condition_json,
    )


@router.get("/row-policies", response_model=list[RowPolicyOut])
async def list_row_policies(session: SessionDep, _: AdminDep, dataset_id: uuid.UUID | None = None) -> list[RowPolicyOut]:
    stmt = select(RowPolicy)
    if dataset_id:
        stmt = stmt.where(RowPolicy.dataset_id == dataset_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [_row_policy_out(p) for p in rows]


@router.post("/row-policies", response_model=RowPolicyOut)
async def create_row_policy(payload: RowPolicyIn, session: SessionDep, admin: AdminDep) -> RowPolicyOut:
    if payload.subject_type not in SUBJECT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"subject_type must be one of {sorted(SUBJECT_TYPES)}")
    ds = await session.get(Dataset, payload.dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    columns = {
        row[0]
        for row in (
            await session.execute(
                select(DatasetColumn.name).where(DatasetColumn.dataset_id == payload.dataset_id)
            )
        ).all()
    }
    if not columns:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "dataset schema columns are required before saving row policies")
    try:
        validate_policy_references(payload.condition_json, columns)
        sql_condition = compile_policy_dsl(payload.condition_json)
    except RowPolicyDslError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid policy: {e}")
    policy = RowPolicy(
        dataset_id=payload.dataset_id, subject_type=payload.subject_type,
        subject_id=payload.subject_id, sql_condition=sql_condition, condition_json=payload.condition_json,
    )
    session.add(policy)
    await session.flush()
    await bump_permission_version(session)
    await bump_permission_version(session, f"row_policy:{payload.dataset_id}")
    await log_event(session, user=admin, event_type="PERMISSION_CHANGED", resource_type="row_policy",
                    resource_id=str(policy.id), input_summary={"dataset_id": str(payload.dataset_id), "sql": sql_condition})
    await session.commit()
    return _row_policy_out(policy)


@router.delete("/row-policies/{policy_id}")
async def delete_row_policy(policy_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    policy = await session.get(RowPolicy, policy_id)
    if policy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "row policy not found")
    dataset_id = policy.dataset_id
    await session.delete(policy)
    await bump_permission_version(session)
    await bump_permission_version(session, f"row_policy:{dataset_id}")
    await log_event(session, user=admin, event_type="PERMISSION_CHANGED", resource_type="row_policy",
                    resource_id=str(policy_id), input_summary={"action": "delete"})
    await session.commit()
    return {"ok": True}


# ------------------------------------------------------------- column masks

class ColumnMaskIn(BaseModel):
    dataset_id: uuid.UUID
    column_name: str
    subject_type: str
    subject_id: uuid.UUID
    mask_type: str


class ColumnMaskOut(BaseModel):
    id: str
    dataset_id: str
    column_name: str
    subject_type: str
    subject_id: str | None
    mask_type: str | None


def _mask_out(m: ColumnPermission) -> ColumnMaskOut:
    return ColumnMaskOut(
        id=str(m.id), dataset_id=str(m.dataset_id), column_name=m.column_name,
        subject_type=m.subject_type, subject_id=str(m.subject_id) if m.subject_id else None,
        mask_type=m.mask_type,
    )


@router.get("/column-masks", response_model=list[ColumnMaskOut])
async def list_column_masks(session: SessionDep, _: AdminDep, dataset_id: uuid.UUID | None = None) -> list[ColumnMaskOut]:
    stmt = select(ColumnPermission)
    if dataset_id:
        stmt = stmt.where(ColumnPermission.dataset_id == dataset_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [_mask_out(m) for m in rows]


@router.post("/column-masks", response_model=ColumnMaskOut)
async def create_column_mask(payload: ColumnMaskIn, session: SessionDep, admin: AdminDep) -> ColumnMaskOut:
    if payload.subject_type not in SUBJECT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"subject_type must be one of {sorted(SUBJECT_TYPES)}")
    if payload.mask_type not in MASK_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"mask_type must be one of {sorted(MASK_TYPES)}")
    ds = await session.get(Dataset, payload.dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    mask = ColumnPermission(
        dataset_id=payload.dataset_id, column_name=payload.column_name,
        subject_type=payload.subject_type, subject_id=payload.subject_id,
        can_view=payload.mask_type != "hidden", mask_type=payload.mask_type,
    )
    session.add(mask)
    await session.flush()
    await bump_permission_version(session)
    await bump_permission_version(session, f"column_mask:{payload.dataset_id}")
    await log_event(session, user=admin, event_type="PERMISSION_CHANGED", resource_type="column_mask",
                    resource_id=str(mask.id), input_summary={"dataset_id": str(payload.dataset_id), "column": payload.column_name, "mask": payload.mask_type})
    await session.commit()
    return _mask_out(mask)


@router.delete("/column-masks/{mask_id}")
async def delete_column_mask(mask_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    mask = await session.get(ColumnPermission, mask_id)
    if mask is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "column mask not found")
    dataset_id = mask.dataset_id
    await session.delete(mask)
    await bump_permission_version(session)
    await bump_permission_version(session, f"column_mask:{dataset_id}")
    await log_event(session, user=admin, event_type="PERMISSION_CHANGED", resource_type="column_mask",
                    resource_id=str(mask_id), input_summary={"action": "delete"})
    await session.commit()
    return {"ok": True}


# ------------------------------------------------------------------ secrets

class SecretIn(BaseModel):
    name: str
    description: str | None = None
    value: str


class SecretOut(BaseModel):
    id: str
    name: str | None
    description: str | None
    created_at: datetime


@router.get("/secrets", response_model=list[SecretOut])
async def list_secrets(session: SessionDep, _: AdminDep) -> list[SecretOut]:
    # Never select/return secret_value.
    rows = (
        await session.execute(
            select(Secret.id, Secret.name, Secret.description, Secret.created_at).order_by(Secret.created_at.desc())
        )
    ).all()
    return [SecretOut(id=str(r.id), name=r.name, description=r.description, created_at=r.created_at) for r in rows]


@router.get("/secrets/manager/status")
async def get_secret_manager_status(_: AdminDep) -> dict:
    return secrets_service.secret_manager_status()


@router.post("/secrets", response_model=SecretOut)
async def create_secret_endpoint(payload: SecretIn, session: SessionDep, admin: AdminDep) -> SecretOut:
    if not payload.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "secret value required")
    secret_id = await secrets_service.create_secret(
        session, payload.value, name=payload.name, description=payload.description
    )
    secret = await session.get(Secret, secret_id)
    await log_event(session, user=admin, event_type="PERMISSION_CHANGED", resource_type="secret",
                    resource_id=str(secret_id), input_summary={"action": "create", "name": payload.name})
    await session.commit()
    return SecretOut(id=str(secret.id), name=secret.name, description=secret.description, created_at=secret.created_at)


@router.delete("/secrets/{secret_id}")
async def delete_secret_endpoint(secret_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    secret = await session.get(Secret, secret_id)
    if secret is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "secret not found")
    await secrets_service.delete_secret(session, secret_id)
    await log_event(session, user=admin, event_type="PERMISSION_CHANGED", resource_type="secret",
                    resource_id=str(secret_id), input_summary={"action": "delete"})
    await session.commit()
    return {"ok": True}


# ----------------------------------------------------------- policies overview

class PoliciesSummaryOut(BaseModel):
    row_policy_count: int
    column_mask_count: int
    acl_grant_count: int


@router.get("/policies/summary", response_model=PoliciesSummaryOut)
async def policies_summary(session: SessionDep, _: AdminDep) -> PoliciesSummaryOut:
    rp = (await session.execute(select(func.count()).select_from(RowPolicy))).scalar() or 0
    cm = (await session.execute(select(func.count()).select_from(ColumnPermission))).scalar() or 0
    acl = (await session.execute(select(func.count()).select_from(ResourceACL))).scalar() or 0
    return PoliciesSummaryOut(row_policy_count=int(rp), column_mask_count=int(cm), acl_grant_count=int(acl))
