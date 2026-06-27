from __future__ import annotations

import uuid
import asyncio
import csv
import io
import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions import service as action_service
from app.actions.execution import execute_action_run
from app.actions.registry import validate_params
from app.audit.models import AuditLog
from app.audit.logger import log_event
from app.auth.models import User
from app.auth.service import get_user_roles
from app.data.models import Dataset
from app.db import SessionLocal
from app.deps import CurrentUserDep, SessionDep, StreamUserDep
from app.governed_query.service import governed_query
from app.notifications.service import create_notification
from app.ontology.models import ActionRun, OntologyAction
from app.permissions.enforcement import bump_permission_version, effective_resource_capabilities, explain_resource_permission
from app.platform.models import ApprovalRequest, Branch, BuildLog, BuildRun, ExportArtifact, ExportRequest, LineageEdge, Project, Resource, ResourceACL, ResourceAccessRequest, ResourceVersion
from app.platform.service import CANONICAL_CAPABILITIES, ensure_default_project, get_resource_for_object, record_lineage, register_resource_version, upsert_resource
from app.storage.fs import default_bucket_uri, get_fs

router = APIRouter(prefix="/platform", tags=["platform"])


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str | None
    created_at: datetime


class ResourceOut(BaseModel):
    id: str
    resource_type: str
    object_id: str | None
    name: str
    parent_resource_id: str | None
    project_id: str | None
    owner_user_id: str | None
    metadata: dict[str, Any] | None
    lifecycle_state: str
    created_at: datetime
    updated_at: datetime


class ResourceVersionOut(BaseModel):
    id: str
    resource_id: str
    version_number: int
    branch_name: str
    state: str
    manifest: dict[str, Any]
    created_by: str | None
    created_at: datetime


class ProjectIn(BaseModel):
    name: str
    description: str | None = None


class FolderIn(BaseModel):
    name: str
    project_id: uuid.UUID | None = None
    parent_resource_id: uuid.UUID | None = None


class ResourceMoveIn(BaseModel):
    project_id: uuid.UUID | None = None
    parent_resource_id: uuid.UUID | None = None


class ResourceTransferIn(BaseModel):
    owner_user_id: uuid.UUID


class ResourceVersionIn(BaseModel):
    branch_name: str = "main"
    state: str = "draft"
    manifest: dict[str, Any] = {}


class AccessRequestIn(BaseModel):
    capabilities: list[str]
    reason: str | None = None


class AccessDecisionIn(BaseModel):
    approve: bool
    note: str | None = None


class ExportRequestIn(BaseModel):
    resource_id: uuid.UUID
    purpose: str
    destination: str | None = None
    details: dict[str, Any] = {}


class ResourceExportRequestIn(BaseModel):
    purpose: str
    destination: str | None = None
    details: dict[str, Any] = {}


class ExportRequestOut(BaseModel):
    id: str
    resource_id: str | None
    requester_id: str | None
    purpose: str
    destination: str | None
    status: str
    approval_request_id: str | None
    details: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None
    artifact_id: str | None = None
    download_url: str | None = None


class ApprovalOut(BaseModel):
    id: str
    resource_id: str | None
    requester_id: str | None
    approval_type: str
    status: str
    details: dict[str, Any]
    decided_by: str | None
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None


class BuildLogOut(BaseModel):
    id: str
    level: str
    message: str
    payload: dict | None
    created_at: datetime


class BranchIn(BaseModel):
    name: str
    project_id: uuid.UUID | None = None
    parent_branch_id: uuid.UUID | None = None


class BranchOut(BaseModel):
    id: str
    name: str
    project_id: str | None
    parent_branch_id: str | None
    status: str
    created_by: str | None
    created_at: datetime
    merged_at: datetime | None


class BranchReviewIn(BaseModel):
    note: str | None = None


def _resource_out(r: Resource) -> ResourceOut:
    return ResourceOut(
        id=str(r.id),
        resource_type=r.resource_type,
        object_id=str(r.object_id) if r.object_id else None,
        name=r.name,
        parent_resource_id=str(r.parent_resource_id) if r.parent_resource_id else None,
        project_id=str(r.project_id) if r.project_id else None,
        owner_user_id=str(r.owner_user_id) if r.owner_user_id else None,
        metadata=r.resource_metadata or {},
        lifecycle_state=r.lifecycle_state,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _branch_out(branch: Branch) -> BranchOut:
    return BranchOut(
        id=str(branch.id),
        name=branch.name,
        project_id=str(branch.project_id) if branch.project_id else None,
        parent_branch_id=str(branch.parent_branch_id) if branch.parent_branch_id else None,
        status=branch.status,
        created_by=str(branch.created_by) if branch.created_by else None,
        created_at=branch.created_at,
        merged_at=branch.merged_at,
    )


def _resource_version_out(version: ResourceVersion) -> ResourceVersionOut:
    return ResourceVersionOut(
        id=str(version.id),
        resource_id=str(version.resource_id),
        version_number=version.version_number,
        branch_name=version.branch_name,
        state=version.state,
        manifest=version.manifest or {},
        created_by=str(version.created_by) if version.created_by else None,
        created_at=version.created_at,
    )


def _export_out(row: ExportRequest) -> ExportRequestOut:
    artifact_id = (row.details or {}).get("artifact_id")
    return ExportRequestOut(
        id=str(row.id),
        resource_id=str(row.resource_id) if row.resource_id else None,
        requester_id=str(row.requester_id) if row.requester_id else None,
        purpose=row.purpose,
        destination=row.destination,
        status=row.status,
        approval_request_id=str(row.approval_request_id) if row.approval_request_id else None,
        details=row.details or {},
        created_at=row.created_at,
        completed_at=row.completed_at,
        artifact_id=artifact_id,
        download_url=f"/api/v1/platform/exports/{row.id}/download" if artifact_id else None,
    )


def _approval_out(row: ApprovalRequest) -> ApprovalOut:
    return ApprovalOut(
        id=str(row.id),
        resource_id=str(row.resource_id) if row.resource_id else None,
        requester_id=str(row.requester_id) if row.requester_id else None,
        approval_type=row.approval_type,
        status=row.status,
        details=row.details or {},
        decided_by=str(row.decided_by) if row.decided_by else None,
        decision_note=row.decision_note,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


async def _create_export_request_for_resource(
    *,
    resource_id: uuid.UUID,
    purpose: str,
    destination: str | None,
    details: dict[str, Any],
    session: AsyncSession,
    user: User,
) -> ExportRequest:
    resource = await session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if "export" not in caps and "manage" not in caps:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing export capability")
    approval = ApprovalRequest(
        resource_id=resource.id,
        requester_id=user.id,
        approval_type="export",
        status="pending",
        details={"purpose": purpose, "destination": destination, **(details or {})},
    )
    session.add(approval)
    await session.flush()
    if resource.owner_user_id:
        await create_notification(
            session,
            user_id=resource.owner_user_id,
            topic="export_approval",
            title=f"Export approval requested: {resource.name}",
            body=purpose,
            resource_type=resource.resource_type,
            resource_id=str(resource.object_id or resource.id),
        )
    export = ExportRequest(
        resource_id=resource.id,
        requester_id=user.id,
        purpose=purpose,
        destination=destination,
        status="pending_approval",
        approval_request_id=approval.id,
        details=details or {},
    )
    session.add(export)
    await session.flush()
    await record_lineage(
        session,
        source_resource_id=resource.id,
        target_resource_id=None,
        edge_type="resource_to_export_request",
        metadata={"export_request_id": str(export.id), "purpose": purpose, "destination": destination},
    )
    await log_event(
        session,
        user=user,
        event_type="EXPORT_REQUESTED",
        resource_type=resource.resource_type,
        resource_id=str(resource.object_id or resource.id),
        input_summary={"purpose": purpose, "destination": destination, "approval_id": str(approval.id)},
    )
    return export


async def _generate_export_artifact(session: AsyncSession, export: ExportRequest, user: User) -> ExportArtifact:
    resource = await session.get(Resource, export.resource_id) if export.resource_id else None
    if resource is None or resource.resource_type != "dataset" or resource.object_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "downloadable exports currently require a dataset resource")
    ds = await session.get(Dataset, resource.object_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")

    requested_format = str((export.details or {}).get("format") or "csv").lower()
    if requested_format not in {"csv", "parquet"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "export format must be csv or parquet")
    sql = f'SELECT * FROM "{ds.schema_name}"."{ds.table_name}"'
    result = await governed_query(
        session,
        user,
        sql,
        dataset_ids=[ds.id],
        capability="export",
        audit_resource_type="dataset_export",
        audit_resource_id=str(export.id),
    )
    watermark = f"mini-foundry export {export.id} generated {datetime.utcnow().isoformat()}Z"
    uri = default_bucket_uri(f"exports/{export.id}/data.{requested_format}")
    fs = get_fs(uri)
    parent = uri.rsplit("/", 1)[0]
    if parent and not fs.exists(parent):
        fs.makedirs(parent, exist_ok=True)
    if requested_format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=result["columns"])
        writer.writeheader()
        for row in result["rows"]:
            writer.writerow({col: row.get(col) for col in result["columns"]})
        with fs.open(uri, "w") as handle:
            handle.write(f"# {watermark}\n")
            handle.write(buffer.getvalue())
    else:
        import pandas as pd

        with fs.open(uri, "wb") as handle:
            pd.DataFrame(result["rows"], columns=result["columns"]).to_parquet(handle, index=False)

    artifact = ExportArtifact(
        export_request_id=export.id,
        storage_uri=uri,
        format=requested_format,
        row_count=int(result["row_count"]),
        watermark=watermark,
    )
    session.add(artifact)
    await session.flush()
    export.status = "completed"
    export.completed_at = datetime.utcnow()
    export.details = {**(export.details or {}), "artifact_id": str(artifact.id), "watermark": watermark}
    await log_event(
        session,
        user=user,
        event_type="EXPORT_GENERATED",
        resource_type=resource.resource_type,
        resource_id=str(resource.object_id),
        output_summary={"export_request_id": str(export.id), "artifact_id": str(artifact.id), "rows": artifact.row_count},
    )
    return artifact


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(session: SessionDep, user: CurrentUserDep) -> list[ProjectOut]:
    await ensure_default_project(session, user)
    rows = list((await session.execute(select(Project).where(Project.deleted_at.is_(None)).order_by(Project.name))).scalars().all())
    await session.commit()
    visible: list[ProjectOut] = []
    for p in rows:
        resource = await get_resource_for_object(session, "project", p.id)
        caps = await effective_resource_capabilities(session, user, resource) if resource is not None else set()
        if p.owner_id != user.id and not ({"view_metadata", "manage"} & caps):
            continue
        visible.append(ProjectOut(id=str(p.id), name=p.name, description=p.description, owner_id=str(p.owner_id) if p.owner_id else None, created_at=p.created_at))
    return visible


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(payload: ProjectIn, session: SessionDep, user: CurrentUserDep) -> ProjectOut:
    project = Project(name=payload.name, description=payload.description, owner_id=user.id)
    session.add(project)
    await session.flush()
    await upsert_resource(session, resource_type="project", object_id=project.id, name=project.name, owner_user_id=user.id, project_id=project.id)
    await log_event(session, user=user, event_type="PROJECT_CREATED", resource_type="project", resource_id=str(project.id))
    await session.commit()
    return ProjectOut(id=str(project.id), name=project.name, description=project.description, owner_id=str(user.id), created_at=project.created_at)


async def _require_project_cap(session, user, project_id: uuid.UUID, capability: str):
    """Load a project + its Resource and enforce a capability on the project resource."""
    project = await session.get(Project, project_id)
    if project is None or project.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    resource = await get_resource_for_object(session, "project", project_id)
    if project.owner_id == user.id:
        return project, resource
    caps = await effective_resource_capabilities(session, user, resource) if resource is not None else set()
    if not ({capability, "manage"} & caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing capability: {capability}")
    return project, resource


class ProjectDetailOut(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str | None
    created_at: datetime | None
    resource_counts: dict[str, int]
    resource_total: int


@router.get("/projects/{project_id}", response_model=ProjectDetailOut)
async def get_project(project_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> ProjectDetailOut:
    project, _ = await _require_project_cap(session, user, project_id, "view_metadata")
    rows = (
        await session.execute(
            select(Resource.resource_type, func.count())
            .where(Resource.project_id == project_id, Resource.deleted_at.is_(None), Resource.resource_type != "project")
            .group_by(Resource.resource_type)
        )
    ).all()
    counts = {rt: int(c) for rt, c in rows}
    return ProjectDetailOut(
        id=str(project.id), name=project.name, description=project.description,
        owner_id=str(project.owner_id) if project.owner_id else None, created_at=project.created_at,
        resource_counts=counts, resource_total=sum(counts.values()),
    )


class ProjectAccessOut(BaseModel):
    id: str
    subject_type: str
    subject_id: str | None
    capabilities: list[str]
    inherit: bool


class ProjectAccessIn(BaseModel):
    subject_type: str
    subject_id: uuid.UUID | None = None
    capabilities: list[str]


@router.get("/projects/{project_id}/access", response_model=list[ProjectAccessOut])
async def list_project_access(project_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[ProjectAccessOut]:
    _, resource = await _require_project_cap(session, user, project_id, "view_metadata")
    if resource is None:
        return []
    rows = (await session.execute(select(ResourceACL).where(ResourceACL.resource_id == resource.id))).scalars().all()
    return [
        ProjectAccessOut(
            id=str(a.id), subject_type=a.subject_type,
            subject_id=str(a.subject_id) if a.subject_id else None,
            capabilities=list(a.capabilities or []), inherit=a.inherit,
        )
        for a in rows
    ]


@router.post("/projects/{project_id}/access", response_model=ProjectAccessOut)
async def grant_project_access(project_id: uuid.UUID, payload: ProjectAccessIn, session: SessionDep, user: CurrentUserDep) -> ProjectAccessOut:
    _, resource = await _require_project_cap(session, user, project_id, "grant")
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project resource not found")
    if payload.subject_type not in ("user", "role", "group", "all_users"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid subject_type")
    invalid = [c for c in payload.capabilities if c not in CANONICAL_CAPABILITIES]
    if invalid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid capabilities: {invalid}")
    existing = (await session.execute(
        select(ResourceACL).where(
            ResourceACL.resource_id == resource.id,
            ResourceACL.subject_type == payload.subject_type,
            ResourceACL.subject_id == payload.subject_id,
        )
    )).scalar_one_or_none()
    if existing is None:
        existing = ResourceACL(resource_id=resource.id, subject_type=payload.subject_type, subject_id=payload.subject_id, capabilities=sorted(set(payload.capabilities)))
        session.add(existing)
    else:
        existing.capabilities = sorted(set(payload.capabilities))
    await session.flush()
    await bump_permission_version(session)
    await log_event(session, user=user, event_type="PERMISSION_CHANGED", resource_type="project", resource_id=str(project_id), input_summary={"subject_type": payload.subject_type, "capabilities": existing.capabilities})
    await session.commit()
    return ProjectAccessOut(id=str(existing.id), subject_type=existing.subject_type, subject_id=str(existing.subject_id) if existing.subject_id else None, capabilities=list(existing.capabilities or []), inherit=existing.inherit)


@router.delete("/projects/{project_id}/access/{acl_id}")
async def revoke_project_access(project_id: uuid.UUID, acl_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    _, resource = await _require_project_cap(session, user, project_id, "grant")
    acl = await session.get(ResourceACL, acl_id)
    if acl is None or (resource is not None and acl.resource_id != resource.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "access grant not found")
    await session.delete(acl)
    await bump_permission_version(session)
    await log_event(session, user=user, event_type="PERMISSION_CHANGED", resource_type="project", resource_id=str(project_id), input_summary={"action": "revoke"})
    await session.commit()
    return {"ok": True}


@router.get("/projects/{project_id}/activity")
async def project_activity(project_id: uuid.UUID, session: SessionDep, user: CurrentUserDep, limit: int = Query(default=100, le=500)) -> dict:
    await _require_project_cap(session, user, project_id, "view_metadata")
    resources = (await session.execute(
        select(Resource).where(Resource.project_id == project_id, Resource.deleted_at.is_(None))
    )).scalars().all()
    ids = {str(r.object_id or r.id) for r in resources}
    ids.add(str(project_id))
    if not ids:
        return {"project_id": str(project_id), "events": []}
    audit_rows = (await session.execute(
        select(AuditLog).where(AuditLog.resource_id.in_(ids)).order_by(AuditLog.created_at.desc()).limit(limit)
    )).scalars().all()
    return {
        "project_id": str(project_id),
        "events": [
            {
                "id": str(a.id), "event_type": a.event_type,
                "resource_type": a.resource_type, "resource_id": a.resource_id,
                "user_id": str(a.user_id) if a.user_id else None,
                "created_at": a.created_at.isoformat(),
            }
            for a in audit_rows
        ],
    }


@router.post("/folders", response_model=ResourceOut, status_code=201)
async def create_folder(payload: FolderIn, session: SessionDep, user: CurrentUserDep) -> ResourceOut:
    folder = await upsert_resource(
        session,
        resource_type="folder",
        object_id=uuid.uuid4(),
        name=payload.name,
        owner_user_id=user.id,
        project_id=payload.project_id,
        parent_resource_id=payload.parent_resource_id,
    )
    await log_event(session, user=user, event_type="RESOURCE_CREATED", resource_type="folder", resource_id=str(folder.id))
    await session.commit()
    return _resource_out(folder)


@router.get("/resources", response_model=list[ResourceOut])
async def search_resources(
    session: SessionDep,
    user: CurrentUserDep,
    q: str = "",
    resource_type: str | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = Query(default=100, le=500),
) -> list[ResourceOut]:
    stmt = select(Resource).where(Resource.deleted_at.is_(None))
    if q:
        stmt = stmt.where(or_(Resource.name.ilike(f"%{q}%"), Resource.resource_type.ilike(f"%{q}%")))
    if resource_type:
        stmt = stmt.where(Resource.resource_type == resource_type)
    if project_id:
        stmt = stmt.where(Resource.project_id == project_id)
    rows = (await session.execute(stmt.order_by(Resource.updated_at.desc()).limit(limit))).scalars().all()
    visible = []
    for resource in rows:
        caps = await effective_resource_capabilities(session, user, resource)
        if {"view_metadata", "manage"} & caps:
            visible.append(resource)
    return [_resource_out(r) for r in visible]


@router.get("/resources/{resource_id}", response_model=ResourceOut)
async def get_resource(resource_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> ResourceOut:
    resource = await session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(404, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not ({"view_metadata", "manage"} & caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing view_metadata capability")
    return _resource_out(resource)


LIFECYCLE_STATES = {"draft", "published", "deprecated", "archived"}


class ResourceLifecycleIn(BaseModel):
    lifecycle_state: str


@router.post("/resources/{resource_id}/lifecycle", response_model=ResourceOut)
async def set_resource_lifecycle(
    resource_id: uuid.UUID, payload: ResourceLifecycleIn, session: SessionDep, user: CurrentUserDep
) -> ResourceOut:
    """Transition a resource's unified lifecycle state (draft/published/
    deprecated/archived). Requires ``publish`` or ``manage`` on the resource."""
    if payload.lifecycle_state not in LIFECYCLE_STATES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"lifecycle_state must be one of {sorted(LIFECYCLE_STATES)}")
    resource = await session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(404, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not ({"publish", "manage"} & caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing publish/manage capability")
    previous = resource.lifecycle_state
    resource.lifecycle_state = payload.lifecycle_state
    resource.updated_at = datetime.utcnow()
    await log_event(
        session,
        user=user,
        event_type="RESOURCE_LIFECYCLE_CHANGED",
        resource_type=resource.resource_type,
        resource_id=str(resource_id),
        input_summary={"from": previous, "to": payload.lifecycle_state},
    )
    await session.commit()
    await session.refresh(resource)
    return _resource_out(resource)


@router.patch("/resources/{resource_id}/move", response_model=ResourceOut)
async def move_resource(resource_id: uuid.UUID, payload: ResourceMoveIn, session: SessionDep, user: CurrentUserDep) -> ResourceOut:
    resource = await session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not (resource.owner_user_id == user.id or "manage" in caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "resource manage capability required")
    resource.project_id = payload.project_id
    resource.parent_resource_id = payload.parent_resource_id
    resource.updated_at = datetime.utcnow()
    await log_event(session, user=user, event_type="RESOURCE_MOVED", resource_type=resource.resource_type, resource_id=str(resource.object_id or resource.id))
    await session.commit()
    return _resource_out(resource)


@router.patch("/resources/{resource_id}/transfer", response_model=ResourceOut)
async def transfer_resource(resource_id: uuid.UUID, payload: ResourceTransferIn, session: SessionDep, user: CurrentUserDep) -> ResourceOut:
    resource = await session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not (resource.owner_user_id == user.id or "manage" in caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "resource manage capability required")
    resource.owner_user_id = payload.owner_user_id
    resource.updated_at = datetime.utcnow()
    acl = (await session.execute(
        select(ResourceACL).where(ResourceACL.resource_id == resource.id, ResourceACL.subject_type == "user", ResourceACL.subject_id == payload.owner_user_id)
    )).scalar_one_or_none()
    if acl is None:
        session.add(ResourceACL(resource_id=resource.id, subject_type="user", subject_id=payload.owner_user_id, capabilities=sorted(CANONICAL_CAPABILITIES)))
    else:
        acl.capabilities = sorted(set(acl.capabilities or []) | CANONICAL_CAPABILITIES)
    await bump_permission_version(session)
    await log_event(session, user=user, event_type="RESOURCE_TRANSFERRED", resource_type=resource.resource_type, resource_id=str(resource.object_id or resource.id), output_summary={"owner_user_id": str(payload.owner_user_id)})
    await session.commit()
    return _resource_out(resource)


@router.delete("/resources/{resource_id}")
async def soft_delete_resource(resource_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    resource = await session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not (resource.owner_user_id == user.id or "manage" in caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "resource manage capability required")
    resource.deleted_at = datetime.utcnow()
    await log_event(session, user=user, event_type="RESOURCE_DELETED", resource_type=resource.resource_type, resource_id=str(resource.object_id or resource.id))
    await session.commit()
    return {"ok": True}


@router.get("/trash", response_model=list[ResourceOut])
async def list_trash(session: SessionDep, user: CurrentUserDep, limit: int = Query(default=100, le=500)) -> list[ResourceOut]:
    stmt = select(Resource).where(Resource.deleted_at.is_not(None)).order_by(Resource.deleted_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    visible: list[Resource] = []
    for resource in rows:
        caps = await effective_resource_capabilities(session, user, resource)
        if resource.owner_user_id == user.id or "manage" in caps:
            visible.append(resource)
    return [_resource_out(row) for row in visible]


@router.post("/resources/{resource_id}/restore", response_model=ResourceOut)
async def restore_resource(resource_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> ResourceOut:
    resource = await session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "deleted resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not (resource.owner_user_id == user.id or "manage" in caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "resource manage capability required")
    resource.deleted_at = None
    resource.updated_at = datetime.utcnow()
    await log_event(session, user=user, event_type="RESOURCE_RESTORED", resource_type=resource.resource_type, resource_id=str(resource.object_id or resource.id))
    await session.commit()
    return _resource_out(resource)


@router.delete("/trash/purge")
async def purge_trash(session: SessionDep, user: CurrentUserDep, retention_days: int = Query(default=30, ge=1, le=365)) -> dict:
    roles = await get_user_roles(session, user.id)
    if "admin" not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    rows = (await session.execute(select(Resource).where(Resource.deleted_at.is_not(None), Resource.deleted_at < cutoff))).scalars().all()
    for row in rows:
        await session.delete(row)
    await log_event(session, user=user, event_type="RESOURCE_TRASH_PURGED", resource_type="resource", output_summary={"count": len(rows), "retention_days": retention_days})
    await session.commit()
    return {"ok": True, "purged": len(rows)}


@router.get("/resources/{resource_id}/activity")
async def resource_activity(resource_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    resource = await session.get(Resource, resource_id)
    if resource is None:
        raise HTTPException(404, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not ({"view_metadata", "manage"} & caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing view_metadata capability")
    audit_rows = (
        await session.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == resource.resource_type, AuditLog.resource_id == str(resource.object_id or resource.id))
            .order_by(AuditLog.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return {
        "resource_id": str(resource_id),
        "events": [
            {
                "id": str(a.id),
                "event_type": a.event_type,
                "user_id": str(a.user_id) if a.user_id else None,
                "input_summary": a.input_summary,
                "output_summary": a.output_summary,
                "created_at": a.created_at.isoformat(),
            }
            for a in audit_rows
        ],
    }


@router.get("/resources/{resource_id}/versions", response_model=list[ResourceVersionOut])
async def list_resource_versions(
    resource_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
    branch_name: str | None = None,
) -> list[ResourceVersionOut]:
    resource = await session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not ({"view_metadata", "manage"} & caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing view_metadata capability")
    stmt = select(ResourceVersion).where(ResourceVersion.resource_id == resource_id)
    if branch_name:
        stmt = stmt.where(ResourceVersion.branch_name == branch_name)
    rows = (await session.execute(stmt.order_by(ResourceVersion.version_number.desc()))).scalars().all()
    return [_resource_version_out(row) for row in rows]


@router.post("/resources/{resource_id}/versions", response_model=ResourceVersionOut, status_code=201)
async def create_resource_version(resource_id: uuid.UUID, payload: ResourceVersionIn, session: SessionDep, user: CurrentUserDep) -> ResourceVersionOut:
    resource = await session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not (resource.owner_user_id == user.id or "manage" in caps or "edit" in caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "resource edit capability required")
    if payload.branch_name != "main":
        branch = (await session.execute(select(Branch).where(Branch.name == payload.branch_name, Branch.status.in_(["active", "review"])))).scalar_one_or_none()
        if branch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "active branch not found")
    version = await register_resource_version(
        session,
        resource=resource,
        created_by=user.id,
        branch_name=payload.branch_name,
        manifest=payload.manifest,
    )
    version.state = payload.state
    await log_event(
        session,
        user=user,
        event_type="RESOURCE_VERSION_CREATED",
        resource_type=resource.resource_type,
        resource_id=str(resource.object_id or resource.id),
        input_summary={"branch_name": payload.branch_name, "state": payload.state},
    )
    await session.commit()
    return _resource_version_out(version)


async def _can_view_resource_node(session, user, resource: Resource | None) -> bool:
    if resource is None or resource.deleted_at is not None:
        return False
    caps = await effective_resource_capabilities(session, user, resource)
    return bool({"view_metadata", "manage"} & caps)


def _edge_matches_branch(edge: LineageEdge, branch_name: str | None) -> bool:
    if not branch_name:
        return True
    meta = edge.edge_metadata or {}
    return meta.get("branch_name") in (None, branch_name)


def _edge_matches_columns(edge: LineageEdge, columns: set[str]) -> bool:
    if not columns:
        return True
    mappings = (edge.edge_metadata or {}).get("column_mappings") or []
    for mapping in mappings:
        if mapping.get("source_column") in columns or mapping.get("target_column") in columns:
            return True
    return False


def _lineage_edge_out(edge: LineageEdge, visible_ids: set[uuid.UUID], include_columns: bool) -> dict:
    metadata = dict(edge.edge_metadata or {})
    if not include_columns:
        metadata.pop("column_mappings", None)
    source_visible = edge.source_resource_id in visible_ids if edge.source_resource_id else False
    target_visible = edge.target_resource_id in visible_ids if edge.target_resource_id else False
    return {
        "id": str(edge.id),
        "source_resource_id": str(edge.source_resource_id) if source_visible else None,
        "source_version_id": str(edge.source_version_id) if source_visible and edge.source_version_id else None,
        "target_resource_id": str(edge.target_resource_id) if target_visible else None,
        "target_version_id": str(edge.target_version_id) if target_visible and edge.target_version_id else None,
        "edge_type": edge.edge_type,
        "metadata": metadata,
        "hidden_source": bool(edge.source_resource_id and not source_visible),
        "hidden_target": bool(edge.target_resource_id and not target_visible),
        "created_at": edge.created_at.isoformat(),
    }


@router.get("/resources/{resource_id}/lineage")
async def resource_lineage(
    resource_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
    direction: str = Query(default="both", pattern="^(upstream|downstream|both)$"),
    depth: int = Query(default=1, ge=1, le=5),
    branch_name: str | None = None,
    include_columns: bool = False,
) -> dict:
    resource = await session.get(Resource, resource_id)
    if resource is None:
        raise HTTPException(404, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not ({"view_metadata", "manage"} & caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing view_metadata capability")

    frontier = {resource_id}
    seen_resources = {resource_id}
    edges_by_id: dict[uuid.UUID, LineageEdge] = {}
    for _ in range(depth):
        clauses = []
        if direction in {"upstream", "both"}:
            clauses.append(LineageEdge.target_resource_id.in_(frontier))
        if direction in {"downstream", "both"}:
            clauses.append(LineageEdge.source_resource_id.in_(frontier))
        if not clauses:
            break
        stmt = select(LineageEdge).where(or_(*clauses)).order_by(LineageEdge.created_at.desc()).limit(500)
        rows = (await session.execute(stmt)).scalars().all()
        next_frontier: set[uuid.UUID] = set()
        for edge in rows:
            if not _edge_matches_branch(edge, branch_name):
                continue
            edges_by_id[edge.id] = edge
            for node_id in (edge.source_resource_id, edge.target_resource_id):
                if node_id and node_id not in seen_resources:
                    seen_resources.add(node_id)
                    next_frontier.add(node_id)
        frontier = next_frontier
        if not frontier:
            break

    resources = {
        r.id: r for r in (
            await session.execute(select(Resource).where(Resource.id.in_(seen_resources)))
        ).scalars().all()
    }
    visible_ids = {rid for rid, row in resources.items() if await _can_view_resource_node(session, user, row)}
    nodes = [
        {
            "id": str(r.id),
            "resource_type": r.resource_type,
            "object_id": str(r.object_id) if r.object_id else None,
            "name": r.name,
            "project_id": str(r.project_id) if r.project_id else None,
        }
        for rid, r in resources.items()
        if rid in visible_ids
    ]
    hidden_ids = seen_resources - visible_ids
    return {
        "resource_id": str(resource_id),
        "direction": direction,
        "depth": depth,
        "branch_name": branch_name,
        "nodes": nodes,
        "edges": [_lineage_edge_out(edge, visible_ids, include_columns) for edge in edges_by_id.values()],
        "hidden_nodes": {"count": len(hidden_ids)},
    }


@router.get("/resources/{resource_id}/impact")
async def resource_impact(
    resource_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
    depth: int = Query(default=3, ge=1, le=5),
    columns: str | None = None,
) -> dict:
    resource = await session.get(Resource, resource_id)
    if resource is None:
        raise HTTPException(404, "resource not found")
    if not await _can_view_resource_node(session, user, resource):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing view_metadata capability")

    column_filter = {c.strip() for c in (columns or "").split(",") if c.strip()}
    frontier = {resource_id}
    seen = {resource_id}
    affected: dict[uuid.UUID, Resource] = {}
    edge_count = 0
    hidden = 0
    for _ in range(depth):
        rows = (await session.execute(
            select(LineageEdge).where(LineageEdge.source_resource_id.in_(frontier)).order_by(LineageEdge.created_at.desc()).limit(500)
        )).scalars().all()
        next_frontier: set[uuid.UUID] = set()
        for edge in rows:
            if not _edge_matches_columns(edge, column_filter):
                continue
            edge_count += 1
            target_id = edge.target_resource_id
            if not target_id or target_id in seen:
                continue
            seen.add(target_id)
            next_frontier.add(target_id)
            target = await session.get(Resource, target_id)
            if await _can_view_resource_node(session, user, target):
                affected[target_id] = target
            else:
                hidden += 1
        frontier = next_frontier
        if not frontier:
            break

    by_type: dict[str, int] = {}
    items = []
    for row in affected.values():
        by_type[row.resource_type] = by_type.get(row.resource_type, 0) + 1
        items.append({
            "id": str(row.id),
            "resource_type": row.resource_type,
            "object_id": str(row.object_id) if row.object_id else None,
            "name": row.name,
            "project_id": str(row.project_id) if row.project_id else None,
        })
    return {
        "resource_id": str(resource_id),
        "depth": depth,
        "columns": sorted(column_filter),
        "affected": items,
        "by_type": by_type,
        "edge_count": edge_count,
        "hidden_nodes": {"count": hidden},
    }


@router.get("/resources/{resource_id}/permissions/explain")
async def explain_permission(resource_id: uuid.UUID, capability: str, session: SessionDep, user: CurrentUserDep) -> dict:
    resource = await session.get(Resource, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not caps:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no access to resource")
    return await explain_resource_permission(session, user, resource_id, capability)


@router.post("/resources/{resource_id}/access-requests", status_code=201)
async def request_access(resource_id: uuid.UUID, payload: AccessRequestIn, session: SessionDep, user: CurrentUserDep) -> dict:
    resource = await session.get(Resource, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    invalid = [cap for cap in payload.capabilities if cap not in CANONICAL_CAPABILITIES]
    if invalid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid capabilities: {', '.join(invalid)}")
    req = ResourceAccessRequest(
        resource_id=resource_id,
        requester_id=user.id,
        requested_capabilities=payload.capabilities,
        reason=payload.reason,
    )
    session.add(req)
    if resource.owner_user_id:
        await create_notification(
            session,
            user_id=resource.owner_user_id,
            topic="access_request",
            title=f"Access requested: {resource.name}",
            body=payload.reason,
            resource_type=resource.resource_type,
            resource_id=str(resource.object_id or resource.id),
        )
    await log_event(session, user=user, event_type="ACCESS_REQUESTED", resource_type=resource.resource_type, resource_id=str(resource.object_id or resource.id), input_summary={"capabilities": payload.capabilities})
    await session.commit()
    return {"id": str(req.id), "status": req.status}


@router.get("/access-requests")
async def list_access_requests(session: SessionDep, user: CurrentUserDep, status_filter: str = "pending") -> dict:
    owned = (await session.execute(select(Resource.id).where(Resource.owner_user_id == user.id))).scalars().all()
    stmt = select(ResourceAccessRequest).where(ResourceAccessRequest.resource_id.in_(list(owned)))
    if status_filter:
        stmt = stmt.where(ResourceAccessRequest.status == status_filter)
    rows = (await session.execute(stmt.order_by(ResourceAccessRequest.created_at.desc()))).scalars().all()
    return {
        "requests": [
            {
                "id": str(r.id),
                "resource_id": str(r.resource_id),
                "requester_id": str(r.requester_id) if r.requester_id else None,
                "capabilities": r.requested_capabilities,
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/access-requests/{request_id}/decision")
async def decide_access_request(request_id: uuid.UUID, payload: AccessDecisionIn, session: SessionDep, user: CurrentUserDep) -> dict:
    req = await session.get(ResourceAccessRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "access request not found")
    resource = await session.get(Resource, req.resource_id)
    if resource is None or resource.owner_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "resource owner required")
    req.status = "approved" if payload.approve else "denied"
    req.decided_by = user.id
    req.decision_note = payload.note
    req.decided_at = datetime.utcnow()
    if payload.approve and req.requester_id:
        acl = (await session.execute(
            select(ResourceACL).where(ResourceACL.resource_id == req.resource_id, ResourceACL.subject_type == "user", ResourceACL.subject_id == req.requester_id)
        )).scalar_one_or_none()
        if acl is None:
            session.add(ResourceACL(resource_id=req.resource_id, subject_type="user", subject_id=req.requester_id, capabilities=req.requested_capabilities))
        else:
            acl.capabilities = sorted(set(acl.capabilities or []) | set(req.requested_capabilities or []))
        await bump_permission_version(session)
    if req.requester_id:
        await create_notification(
            session,
            user_id=req.requester_id,
            topic="access_request",
            title=f"Access request {req.status}",
            body=payload.note,
            resource_type=resource.resource_type,
            resource_id=str(resource.object_id or resource.id),
        )
    await log_event(session, user=user, event_type="ACCESS_REQUEST_DECIDED", resource_type=resource.resource_type, resource_id=str(resource.object_id or resource.id), output_summary={"approved": payload.approve, "request_id": str(req.id)})
    await session.commit()
    return {"ok": True, "status": req.status}


@router.post("/exports", response_model=ExportRequestOut, status_code=201)
async def create_export_request(payload: ExportRequestIn, session: SessionDep, user: CurrentUserDep) -> ExportRequestOut:
    export = await _create_export_request_for_resource(
        resource_id=payload.resource_id,
        purpose=payload.purpose,
        destination=payload.destination,
        details=payload.details,
        session=session,
        user=user,
    )
    await session.commit()
    return _export_out(export)


@router.post("/resources/{resource_id}/exports", response_model=ExportRequestOut, status_code=201)
async def create_resource_export_request(resource_id: uuid.UUID, payload: ResourceExportRequestIn, session: SessionDep, user: CurrentUserDep) -> ExportRequestOut:
    export = await _create_export_request_for_resource(
        resource_id=resource_id,
        purpose=payload.purpose,
        destination=payload.destination,
        details=payload.details,
        session=session,
        user=user,
    )
    await session.commit()
    return _export_out(export)


@router.get("/exports", response_model=list[ExportRequestOut])
async def list_export_requests(session: SessionDep, user: CurrentUserDep, status_filter: str | None = None) -> list[ExportRequestOut]:
    roles = await get_user_roles(session, user.id)
    stmt = select(ExportRequest)
    if "admin" not in roles:
        owned_resource_ids = (await session.execute(select(Resource.id).where(Resource.owner_user_id == user.id))).scalars().all()
        stmt = stmt.where((ExportRequest.requester_id == user.id) | (ExportRequest.resource_id.in_(list(owned_resource_ids))))
    if status_filter:
        stmt = stmt.where(ExportRequest.status == status_filter)
    rows = (await session.execute(stmt.order_by(ExportRequest.created_at.desc()).limit(200))).scalars().all()
    return [_export_out(row) for row in rows]


@router.get("/approvals", response_model=list[ApprovalOut])
async def list_approvals(session: SessionDep, user: CurrentUserDep, status_filter: str | None = "pending") -> list[ApprovalOut]:
    roles = await get_user_roles(session, user.id)
    stmt = select(ApprovalRequest)
    if "admin" not in roles:
        owned_resource_ids = (await session.execute(select(Resource.id).where(Resource.owner_user_id == user.id))).scalars().all()
        stmt = stmt.where((ApprovalRequest.requester_id == user.id) | (ApprovalRequest.resource_id.in_(list(owned_resource_ids))))
    if status_filter:
        stmt = stmt.where(ApprovalRequest.status == status_filter)
    rows = (await session.execute(stmt.order_by(ApprovalRequest.created_at.desc()).limit(200))).scalars().all()
    return [_approval_out(row) for row in rows]


async def _apply_action_approval_decision(
    session: AsyncSession,
    *,
    approval: ApprovalRequest,
    approved: bool,
    decider: User,
    note: str | None,
) -> dict[str, Any]:
    action_run = (
        await session.execute(select(ActionRun).where(ActionRun.approval_request_id == approval.id))
    ).scalar_one_or_none()
    if action_run is None:
        return {"action_run_status": "missing"}
    if action_run.status != "pending_approval":
        return {"action_run_id": str(action_run.id), "action_run_status": action_run.status}

    if not approved:
        action_run.status = "rejected"
        action_run.error = note or "approval rejected"
        action_run.finished_at = datetime.utcnow()
        action_run.output = {**(action_run.output or {}), "decision": "rejected"}
        if action_run.user_id:
            await create_notification(
                session,
                user_id=action_run.user_id,
                topic="action_approval",
                title="Action approval rejected",
                body=note,
                resource_type="action",
                resource_id=str(action_run.action_id),
            )
        await log_event(
            session,
            user=decider,
            event_type="ACTION_APPROVAL_REJECTED",
            resource_type="action",
            resource_id=str(action_run.action_id),
            output_summary={"action_run_id": str(action_run.id), "approval_id": str(approval.id)},
        )
        return {"action_run_id": str(action_run.id), "action_run_status": action_run.status}

    action = await session.get(OntologyAction, action_run.action_id)
    requester = await session.get(User, action_run.user_id) if action_run.user_id else None
    if action is None or requester is None:
        action_run.status = "failed"
        action_run.error = "action or requester no longer exists"
        action_run.finished_at = datetime.utcnow()
        return {"action_run_id": str(action_run.id), "action_run_status": action_run.status, "error": action_run.error}
    if not action.enabled:
        action_run.status = "failed"
        action_run.error = "action disabled"
        action_run.finished_at = datetime.utcnow()
        return {"action_run_id": str(action_run.id), "action_run_status": action_run.status, "error": action_run.error}
    if not await action_service.user_can_run_action(session, requester, action):
        action_run.status = "failed"
        action_run.error = "requester no longer has permission to run this action"
        action_run.finished_at = datetime.utcnow()
        return {"action_run_id": str(action_run.id), "action_run_status": action_run.status, "error": action_run.error}

    params = action_run.input or approval.details.get("params") or {}
    try:
        validate_params(action.input_schema, params)
    except ValueError as e:
        action_run.status = "failed"
        action_run.error = f"invalid params: {e}"
        action_run.finished_at = datetime.utcnow()
        return {"action_run_id": str(action_run.id), "action_run_status": action_run.status, "error": action_run.error}
    precondition_failures = action_service.evaluate_preconditions(action.preconditions, params)
    if precondition_failures:
        action_run.status = "failed"
        action_run.error = "action preconditions failed"
        action_run.output = {**(action_run.output or {}), "precondition_failures": precondition_failures}
        action_run.finished_at = datetime.utcnow()
        return {"action_run_id": str(action_run.id), "action_run_status": action_run.status, "error": action_run.error}

    try:
        result = await execute_action_run(
            session,
            user=requester,
            action=action,
            action_run=action_run,
            params=params,
        )
    except HTTPException as e:
        action_run.status = "failed"
        action_run.error = str(e.detail)
        action_run.finished_at = action_run.finished_at or datetime.utcnow()
        await log_event(
            session,
            user=decider,
            event_type="ACTION_APPROVED_EXECUTION_FAILED",
            resource_type="action",
            resource_id=str(action.id),
            output_summary={"action_run_id": str(action_run.id), "approval_id": str(approval.id), "error": action_run.error},
        )
        return {"action_run_id": str(action_run.id), "action_run_status": action_run.status, "error": action_run.error}

    await log_event(
        session,
        user=decider,
        event_type="ACTION_APPROVED_EXECUTED",
        resource_type="action",
        resource_id=str(action.id),
        output_summary={"action_run_id": str(action_run.id), "approval_id": str(approval.id), "status": result.get("status")},
    )
    if action_run.user_id:
        await create_notification(
            session,
            user_id=action_run.user_id,
            topic="action_approval",
            title="Approved action completed",
            body=f"Action run {action_run.id} finished with status {action_run.status}.",
            resource_type="action",
            resource_id=str(action.id),
        )
    return {"action_run_id": str(action_run.id), "action_run_status": action_run.status, **result}


@router.post("/approvals/{approval_id}/decision")
async def decide_approval(approval_id: uuid.UUID, payload: AccessDecisionIn, session: SessionDep, user: CurrentUserDep) -> dict:
    approval = await session.get(ApprovalRequest, approval_id)
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "approval not found")
    roles = await get_user_roles(session, user.id)
    resource = await session.get(Resource, approval.resource_id) if approval.resource_id else None
    if "admin" not in roles and (resource is None or resource.owner_user_id != user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "resource owner or admin required")
    approval.status = "approved" if payload.approve else "rejected"
    approval.decided_by = user.id
    approval.decision_note = payload.note
    approval.decided_at = datetime.utcnow()
    if approval.approval_type == "export":
        exports = (
            await session.execute(select(ExportRequest).where(ExportRequest.approval_request_id == approval.id))
        ).scalars().all()
        for export in exports:
            export.status = "approved" if payload.approve else "rejected"
            if payload.approve:
                requester = await session.get(User, export.requester_id) if export.requester_id else user
                await _generate_export_artifact(session, export, requester or user)
                if export.requester_id:
                    await create_notification(
                        session,
                        user_id=export.requester_id,
                        topic="export",
                        title="Export ready",
                        body=export.purpose,
                        resource_type="export_request",
                        resource_id=str(export.id),
                    )
            elif export.requester_id:
                await create_notification(
                    session,
                    user_id=export.requester_id,
                    topic="export",
                    title="Export rejected",
                    body=payload.note,
                    resource_type="export_request",
                    resource_id=str(export.id),
                )
    action_result: dict[str, Any] | None = None
    if approval.approval_type == "action":
        action_result = await _apply_action_approval_decision(
            session,
            approval=approval,
            approved=payload.approve,
            decider=user,
            note=payload.note,
        )
    await log_event(session, user=user, event_type="APPROVAL_DECIDED", resource_type=resource.resource_type if resource else "approval", resource_id=str(resource.object_id or resource.id) if resource else str(approval.id), output_summary={"approved": payload.approve, "approval_id": str(approval.id)})
    await session.commit()
    return {"ok": True, "status": approval.status, **({"action": action_result} if action_result else {})}


@router.post("/exports/{export_id}/generate", response_model=ExportRequestOut)
async def generate_export(export_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> ExportRequestOut:
    export = await session.get(ExportRequest, export_id)
    if export is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "export not found")
    if export.requester_id != user.id:
        roles = await get_user_roles(session, user.id)
        if "admin" not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "export requester or admin required")
    if export.status not in {"approved", "completed"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "export must be approved before generation")
    if not (export.details or {}).get("artifact_id"):
        await _generate_export_artifact(session, export, user)
    await session.commit()
    return _export_out(export)


@router.get("/exports/{export_id}/download")
async def download_export(export_id: uuid.UUID, session: SessionDep, user: CurrentUserDep):
    export = await session.get(ExportRequest, export_id)
    if export is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "export not found")
    if export.requester_id != user.id:
        roles = await get_user_roles(session, user.id)
        if "admin" not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "export requester or admin required")
    artifact = (
        await session.execute(select(ExportArtifact).where(ExportArtifact.export_request_id == export_id))
    ).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "export artifact not generated")
    fs = get_fs(artifact.storage_uri)

    def _iter():
        with fs.open(artifact.storage_uri, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk

    media_type = "text/csv" if artifact.format == "csv" else "application/vnd.apache.parquet"
    return StreamingResponse(
        _iter(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="export-{export_id}.{artifact.format}"'},
    )


@router.get("/branches", response_model=list[BranchOut])
async def list_branches(
    session: SessionDep,
    user: CurrentUserDep,
    project_id: uuid.UUID | None = None,
    status_filter: str | None = None,
) -> list[BranchOut]:
    roles = await get_user_roles(session, user.id)
    stmt = select(Branch)
    if "admin" not in roles:
        stmt = stmt.where(Branch.created_by == user.id)
    if project_id:
        stmt = stmt.where(Branch.project_id == project_id)
    if status_filter:
        stmt = stmt.where(Branch.status == status_filter)
    rows = (await session.execute(stmt.order_by(Branch.created_at.desc()))).scalars().all()
    return [_branch_out(row) for row in rows]


@router.post("/branches", response_model=BranchOut, status_code=201)
async def create_branch(payload: BranchIn, session: SessionDep, user: CurrentUserDep) -> BranchOut:
    name = payload.name.strip()
    if not name or "/" in name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "branch name is required and cannot contain '/'")
    existing = (
        await session.execute(
            select(Branch).where(
                Branch.name == name,
                Branch.project_id == payload.project_id,
                Branch.status.in_(["active", "review"]),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "active branch with this name already exists")
    branch = Branch(
        name=name,
        project_id=payload.project_id,
        parent_branch_id=payload.parent_branch_id,
        created_by=user.id,
        status="active",
    )
    session.add(branch)
    await log_event(session, user=user, event_type="BRANCH_CREATED", resource_type="branch", resource_id=name, input_summary={"project_id": str(payload.project_id) if payload.project_id else None})
    await session.commit()
    return _branch_out(branch)


async def _branch_versions(session: AsyncSession, branch: Branch) -> list[ResourceVersion]:
    stmt = (
        select(ResourceVersion)
        .join(Resource, Resource.id == ResourceVersion.resource_id)
        .where(ResourceVersion.branch_name == branch.name)
    )
    if branch.project_id is not None:
        stmt = stmt.where(Resource.project_id == branch.project_id)
    return list((await session.execute(stmt.order_by(ResourceVersion.resource_id, ResourceVersion.version_number.desc()))).scalars().all())


async def _latest_main_version_after(session: AsyncSession, resource_id: uuid.UUID, created_at: datetime) -> ResourceVersion | None:
    return (
        await session.execute(
            select(ResourceVersion)
            .where(
                ResourceVersion.resource_id == resource_id,
                ResourceVersion.branch_name == "main",
                ResourceVersion.created_at > created_at,
            )
            .order_by(ResourceVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _require_branch_owner_or_admin(session: AsyncSession, user: CurrentUserDep, branch: Branch) -> None:
    roles = await get_user_roles(session, user.id)
    if branch.created_by == user.id or "admin" in roles:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "branch owner or admin required")


@router.get("/branches/{branch_id}/compare")
async def compare_branch(branch_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:  # noqa: ARG001
    branch = await session.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "branch not found")
    await _require_branch_owner_or_admin(session, user, branch)
    versions = await _branch_versions(session, branch)
    latest_by_resource: dict[uuid.UUID, ResourceVersion] = {}
    for version in versions:
        latest_by_resource.setdefault(version.resource_id, version)
    changes = []
    conflicts = []
    for resource_id, version in latest_by_resource.items():
        resource = await session.get(Resource, resource_id)
        changed_main = await _latest_main_version_after(session, resource_id, branch.created_at)
        change = {
            "resource_id": str(resource_id),
            "resource_type": resource.resource_type if resource else None,
            "name": resource.name if resource else version.manifest.get("name"),
            "branch_version_id": str(version.id),
            "branch_version_number": version.version_number,
            "main_changed_after_branch": bool(changed_main),
        }
        changes.append(change)
        if changed_main:
            conflicts.append({**change, "main_version_id": str(changed_main.id), "main_version_number": changed_main.version_number})
    return {"branch": _branch_out(branch).model_dump(), "changes": changes, "conflicts": conflicts, "mergeable": not conflicts}


@router.post("/branches/{branch_id}/review")
async def request_branch_review(branch_id: uuid.UUID, payload: BranchReviewIn, session: SessionDep, user: CurrentUserDep) -> dict:
    branch = await session.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "branch not found")
    await _require_branch_owner_or_admin(session, user, branch)
    branch.status = "review"
    await log_event(session, user=user, event_type="BRANCH_REVIEW_REQUESTED", resource_type="branch", resource_id=str(branch.id), input_summary={"note": payload.note})
    await session.commit()
    return {"ok": True, "status": branch.status}


@router.post("/branches/{branch_id}/merge")
async def merge_branch(branch_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    branch = await session.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "branch not found")
    await _require_branch_owner_or_admin(session, user, branch)
    if branch.status not in {"active", "review"}:
        raise HTTPException(status.HTTP_409_CONFLICT, f"branch is {branch.status}")
    comparison = await compare_branch(branch_id, session, user)
    if comparison["conflicts"]:
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": "branch has conflicts", "conflicts": comparison["conflicts"]})
    merged_versions = []
    for change in comparison["changes"]:
        resource = await session.get(Resource, uuid.UUID(change["resource_id"]))
        branch_version = await session.get(ResourceVersion, uuid.UUID(change["branch_version_id"]))
        if resource is None or branch_version is None:
            continue
        caps = await effective_resource_capabilities(session, user, resource)
        if not (resource.owner_user_id == user.id or "manage" in caps):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing manage capability for resource {resource.id}")
        main_version = await register_resource_version(
            session,
            resource=resource,
            created_by=user.id,
            branch_name="main",
            manifest={
                **(branch_version.manifest or {}),
                "merged_from_branch": branch.name,
                "merged_from_version_id": str(branch_version.id),
            },
        )
        merged_versions.append(str(main_version.id))
    branch.status = "merged"
    branch.merged_at = datetime.utcnow()
    await log_event(session, user=user, event_type="BRANCH_MERGED", resource_type="branch", resource_id=str(branch.id), output_summary={"merged_versions": merged_versions})
    await session.commit()
    return {"ok": True, "status": branch.status, "merged_versions": merged_versions}


@router.post("/branches/{branch_id}/abandon")
async def abandon_branch(branch_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    branch = await session.get(Branch, branch_id)
    if branch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "branch not found")
    await _require_branch_owner_or_admin(session, user, branch)
    if branch.status == "merged":
        raise HTTPException(status.HTTP_409_CONFLICT, "merged branches cannot be abandoned")
    branch.status = "abandoned"
    await log_event(session, user=user, event_type="BRANCH_ABANDONED", resource_type="branch", resource_id=str(branch.id))
    await session.commit()
    return {"ok": True, "status": branch.status}


def _build_log_out(row: BuildLog) -> BuildLogOut:
    return BuildLogOut(
        id=str(row.id),
        level=row.level,
        message=row.message,
        payload=row.payload,
        created_at=row.created_at,
    )


async def _require_build_visible(session: AsyncSession, build_id: uuid.UUID, user: CurrentUserDep) -> BuildRun:
    build = await session.get(BuildRun, build_id)
    if build is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "build run not found")
    if build.created_by is not None and build.created_by != user.id:
        roles = await get_user_roles(session, user.id)
        if "admin" not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "not your build run")
    return build


@router.get("/build-runs/{build_id}/stream")
async def stream_build_run(build_id: uuid.UUID, user: StreamUserDep, interval_seconds: float = 2.0) -> StreamingResponse:
    async with SessionLocal() as session:
        await _require_build_visible(session, build_id, user)
    interval = max(1.0, min(interval_seconds, 30.0))

    async def events():
        sent_log_ids: set[str] = set()
        last_status: str | None = None
        while True:
            chunks: list[str] = []
            done = False
            async with SessionLocal() as stream_session:
                build = await stream_session.get(BuildRun, build_id)
                if build is None:
                    chunks.append(f"event: error\ndata: {json.dumps({'message': 'build run not found'})}\n\n")
                    done = True
                else:
                    status_payload = {
                        "id": str(build.id),
                        "status": build.status,
                        "error_summary": build.error_summary,
                        "started_at": build.started_at.isoformat() if build.started_at else None,
                        "finished_at": build.finished_at.isoformat() if build.finished_at else None,
                    }
                    if build.status != last_status:
                        last_status = build.status
                        chunks.append(f"event: status\ndata: {json.dumps(status_payload)}\n\n")
                    logs = (
                        await stream_session.execute(
                            select(BuildLog).where(BuildLog.build_run_id == build_id).order_by(BuildLog.created_at.asc()).limit(500)
                        )
                    ).scalars().all()
                    for log in logs:
                        key = str(log.id)
                        if key in sent_log_ids:
                            continue
                        sent_log_ids.add(key)
                        chunks.append(f"event: log\ndata: {json.dumps(_build_log_out(log).model_dump(mode='json'))}\n\n")
                    if build.status in {"succeeded", "failed", "cancelled"}:
                        chunks.append(f"event: done\ndata: {json.dumps(status_payload)}\n\n")
                        done = True
            for chunk in chunks:
                yield chunk
            if done:
                return
            await asyncio.sleep(interval)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
