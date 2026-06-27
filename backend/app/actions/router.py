import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.actions import service
from app.actions.registry import (
    WORKFLOWS,
    get_workflow,
    list_workflows,
    validate_params,
)
from app.actions.execution import execute_action_run
from app.audit.logger import log_event
from app.deps import AdminDep, CurrentUserDep, SessionDep
from app.ontology.models import ActionPermission, ActionRun, OntologyAction
from app.notifications.service import create_notification
from app.platform.models import ApprovalRequest, ResourceACL
from app.platform.service import get_resource_for_object, upsert_resource


router = APIRouter(prefix="/actions", tags=["actions"])
admin_router = APIRouter(prefix="/admin", tags=["actions"])


class TriggerIn(BaseModel):
    action_name: str
    params: dict[str, Any] = {}
    context: dict[str, Any] | None = None
    idempotency_key: str | None = None


class ActionOut(BaseModel):
    id: str
    name: str
    workflow_key: str
    change_type: str = "update"
    description: str | None
    input_schema: dict | None
    object_type: str | None
    requires_capability: str
    approval_required: bool = False
    preconditions: dict | None = None
    enabled: bool
    validation_rules: list | None = None
    webhook_url: str | None = None
    can_run: bool | None = None
    permission_explanation: str | None = None


class ActionIn(BaseModel):
    name: str
    workflow_key: str
    change_type: str = "update"
    description: str | None = None
    input_schema: dict | None = None
    object_type: str | None = None
    requires_capability: str = "can_run_action"
    approval_required: bool = False
    preconditions: dict[str, Any] | None = None
    enabled: bool = True
    validation_rules: list | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None


class GrantActionIn(BaseModel):
    action_id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID | None = None
    can_run: bool = True


class ActionPreviewIn(BaseModel):
    action_name: str
    params: dict[str, Any] = {}


class ActionPreviewOut(BaseModel):
    action_id: str
    action_name: str
    allowed: bool
    approval_required: bool
    preconditions_ok: bool
    missing_preconditions: list[str] = []
    side_effects: list[dict[str, Any]] = []
    required_capability: str


def _action_out(a: OntologyAction, *, can_run: bool | None = None, permission_explanation: str | None = None) -> ActionOut:
    return ActionOut(
        id=str(a.id), name=a.name, workflow_key=a.workflow_key,
        change_type=a.change_type or "update",
        description=a.description, input_schema=a.input_schema,
        object_type=a.object_type, requires_capability=a.requires_capability,
        approval_required=bool(a.approval_required),
        preconditions=a.preconditions,
        enabled=a.enabled,
        validation_rules=a.validation_rules,
        webhook_url=a.webhook_url,
        can_run=can_run,
        permission_explanation=permission_explanation,
    )


@router.get("", response_model=list[ActionOut])
async def list_runnable_actions(
    session: SessionDep,
    user: CurrentUserDep,
    object_type: str | None = None,
) -> list[ActionOut]:
    stmt = select(OntologyAction).where(OntologyAction.enabled.is_(True)).order_by(OntologyAction.name)
    rows = (await session.execute(stmt)).scalars().all()
    out: list[ActionOut] = []
    for action in rows:
        if object_type and action.object_type not in {None, object_type}:
            continue
        can_run = await service.user_can_run_action(session, user, action)
        required = service.canonical_action_capability(action.requires_capability)
        out.append(
            _action_out(
                action,
                can_run=can_run,
                permission_explanation=(
                    "Allowed by action resource capability"
                    if can_run
                    else f"Requires `{required}` on this action resource"
                ),
            )
        )
    return out


@router.post("/trigger")
async def trigger(payload: TriggerIn, session: SessionDep, user: CurrentUserDep) -> dict:
    action = (await session.execute(
        select(OntologyAction).where(OntologyAction.name == payload.action_name)
    )).scalar_one_or_none()
    if action is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown action: {payload.action_name}")
    if not action.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "action disabled")

    can_run = await service.user_can_run_action(session, user, action)
    if not can_run:
        await log_event(
            session, user=user, event_type="ACTION_TRIGGERED",
            resource_type="action", resource_id=str(action.id),
            input_summary={"action": action.name, "denied": True},
        )
        await session.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no permission to run this action")

    try:
        validate_params(action.input_schema, payload.params)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid params: {e}")
    precondition_failures = service.evaluate_preconditions(action.preconditions, payload.params)
    if precondition_failures:
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": "action preconditions failed", "failures": precondition_failures})

    if payload.idempotency_key:
        existing_run = (await session.execute(
            select(ActionRun).where(
                ActionRun.action_id == action.id,
                ActionRun.user_id == user.id,
                ActionRun.idempotency_key == payload.idempotency_key,
                ActionRun.status.in_(["running", "succeeded", "queued", "pending_approval"]),
            )
        )).scalar_one_or_none()
        if existing_run is not None:
            return {"status": existing_run.status, "action_run_id": str(existing_run.id), "output": existing_run.output}

    action_run = ActionRun(
        action_id=action.id,
        user_id=user.id,
        status="pending_approval" if action.approval_required else "running",
        idempotency_key=payload.idempotency_key,
        input=payload.params,
    )
    session.add(action_run)
    await session.flush()
    action_resource = await get_resource_for_object(session, "ontology_action", action.id)

    if action.approval_required:
        approval = ApprovalRequest(
            resource_id=action_resource.id if action_resource else None,
            requester_id=user.id,
            approval_type="action",
            status="pending",
            details={
                "action_id": str(action.id),
                "action_run_id": str(action_run.id),
                "action_name": action.name,
                "params": payload.params,
                "context": payload.context or {},
            },
        )
        session.add(approval)
        await session.flush()
        action_run.approval_request_id = approval.id
        action_run.output = {"approval_request_id": str(approval.id)}
        if action_resource and action_resource.owner_user_id:
            await create_notification(
                session,
                user_id=action_resource.owner_user_id,
                topic="action_approval",
                title=f"Action approval requested: {action.name}",
                body=None,
                resource_type="action",
                resource_id=str(action.id),
            )
        await log_event(
            session, user=user, event_type="ACTION_APPROVAL_REQUESTED",
            resource_type="action", resource_id=str(action.id),
            input_summary={"action": action.name, "action_run_id": str(action_run.id), "approval_id": str(approval.id)},
        )
        await session.commit()
        return {"status": "pending_approval", "action_run_id": str(action_run.id), "approval_request_id": str(approval.id)}

    try:
        result = await execute_action_run(
            session,
            user=user,
            action=action,
            action_run=action_run,
            params=payload.params,
        )
    except HTTPException:
        await session.commit()
        raise
    await session.commit()
    return result


@router.post("/preview", response_model=ActionPreviewOut)
async def preview_action(payload: ActionPreviewIn, session: SessionDep, user: CurrentUserDep) -> ActionPreviewOut:
    action = (await session.execute(
        select(OntologyAction).where(OntologyAction.name == payload.action_name)
    )).scalar_one_or_none()
    if action is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown action: {payload.action_name}")
    allowed = action.enabled and await service.user_can_run_action(session, user, action)
    try:
        validate_params(action.input_schema, payload.params)
        validation_failures: list[str] = []
    except ValueError as e:
        validation_failures = [str(e)]
    precondition_failures = service.evaluate_preconditions(action.preconditions, payload.params)
    if action.object_type:
        side_effects = [
            {
                "type": "ontology_writeback",
                "object_type": action.object_type,
                "workflow_key": action.workflow_key,
                "requires_approval": action.approval_required,
            }
        ]
    else:
        side_effects = [
            {
                "type": "workflow",
                "workflow_key": action.workflow_key,
                "async": bool(action.workflow_key in WORKFLOWS and not get_workflow(action.workflow_key)["sync"]),
                "requires_approval": action.approval_required,
            }
        ]
    return ActionPreviewOut(
        action_id=str(action.id),
        action_name=action.name,
        allowed=allowed,
        approval_required=action.approval_required,
        preconditions_ok=not validation_failures and not precondition_failures,
        missing_preconditions=validation_failures + precondition_failures,
        side_effects=side_effects,
        required_capability=service.canonical_action_capability(action.requires_capability),
    )


@router.get("/runs")
async def list_action_runs(session: SessionDep, user: CurrentUserDep, limit: int = 100) -> dict:
    rows = (await session.execute(
        select(ActionRun).where(ActionRun.user_id == user.id).order_by(ActionRun.created_at.desc()).limit(limit)
    )).scalars().all()
    return {
        "runs": [
            {
                "id": str(r.id),
                "action_id": str(r.action_id) if r.action_id else None,
                "status": r.status,
                "idempotency_key": r.idempotency_key,
                "input": r.input,
                "output": r.output,
                "before_state": r.before_state,
                "after_state": r.after_state,
                "writeback_destination": r.writeback_destination,
                "approval_request_id": str(r.approval_request_id) if r.approval_request_id else None,
                "error": r.error,
                "created_at": r.created_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ]
    }


# ----- admin workflows + actions ----------------------------------------


@admin_router.get("/workflows")
async def workflows_list(_: AdminDep) -> dict:
    return {"workflows": list_workflows()}


@admin_router.get("/ontology/actions", response_model=list[ActionOut])
async def list_actions(session: SessionDep, _: AdminDep) -> list[ActionOut]:
    rows = (await session.execute(
        select(OntologyAction).order_by(OntologyAction.name)
    )).scalars().all()
    return [_action_out(a) for a in rows]


@admin_router.post("/ontology/actions", response_model=ActionOut)
async def create_action(payload: ActionIn, session: SessionDep, admin: AdminDep) -> ActionOut:
    if payload.workflow_key not in WORKFLOWS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown workflow_key: {payload.workflow_key}")
    if payload.change_type not in {"create", "update", "delete"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "change_type must be create|update|delete")
    a = OntologyAction(**payload.model_dump())
    session.add(a)
    await session.flush()
    await upsert_resource(
        session,
        resource_type="ontology_action",
        object_id=a.id,
        name=a.name,
        owner_user_id=admin.id,
        metadata={"workflow_key": a.workflow_key, "object_type": a.object_type},
    )
    await log_event(
        session, user=admin, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_action", resource_id=str(a.id),
        input_summary={"action": "create", **payload.model_dump()},
    )
    await session.commit()
    return _action_out(a)


class ActionPatchIn(BaseModel):
    change_type: str | None = None
    validation_rules: list | None = None
    approval_required: bool | None = None
    preconditions: dict[str, Any] | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    enabled: bool | None = None


@admin_router.patch("/ontology/actions/{action_id}", response_model=ActionOut)
async def patch_action(
    action_id: uuid.UUID, payload: ActionPatchIn, session: SessionDep, admin: AdminDep
) -> ActionOut:
    a = await session.get(OntologyAction, action_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "action not found")
    if payload.change_type is not None:
        if payload.change_type not in {"create", "update", "delete"}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "change_type must be create|update|delete")
        a.change_type = payload.change_type
    if payload.validation_rules is not None:
        a.validation_rules = payload.validation_rules or None
    if payload.approval_required is not None:
        a.approval_required = payload.approval_required
    if payload.preconditions is not None:
        a.preconditions = payload.preconditions or None
    if payload.webhook_url is not None:
        a.webhook_url = payload.webhook_url or None
    if payload.webhook_secret is not None:
        a.webhook_secret = payload.webhook_secret or None
    if payload.enabled is not None:
        a.enabled = payload.enabled
    await upsert_resource(
        session,
        resource_type="ontology_action",
        object_id=a.id,
        name=a.name,
        owner_user_id=admin.id,
        metadata={
            "workflow_key": a.workflow_key,
            "object_type": a.object_type,
            "approval_required": a.approval_required,
            "enabled": a.enabled,
        },
    )
    await log_event(
        session, user=admin, event_type="ONTOLOGY_EDITED",
        resource_type="ontology_action", resource_id=str(a.id),
        input_summary={"action": "patch", **payload.model_dump(exclude_unset=True)},
    )
    await session.commit()
    return _action_out(a)


@admin_router.delete("/ontology/actions/{action_id}")
async def delete_action(action_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    a = await session.get(OntologyAction, action_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "action not found")
    await session.delete(a)
    await session.commit()
    return {"ok": True}


@admin_router.post("/ontology/actions/grant")
async def grant_action_perm(
    payload: GrantActionIn, session: SessionDep, admin: AdminDep,
) -> dict:
    a = await session.get(OntologyAction, payload.action_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "action not found")
    if payload.subject_type not in {"user", "role", "group", "all_users"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "subject_type must be user|role|group|all_users")
    if payload.subject_type != "all_users" and payload.subject_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "subject_id required")
    existing = (await session.execute(
        select(ActionPermission).where(
            ActionPermission.action_id == payload.action_id,
            ActionPermission.subject_type == payload.subject_type,
            ActionPermission.subject_id == payload.subject_id,
        )
    )).scalar_one_or_none()
    if existing is None:
        session.add(ActionPermission(**payload.model_dump()))
    else:
        existing.can_run = payload.can_run
    from app.permissions.enforcement import bump_permission_version
    resource = await get_resource_for_object(session, "ontology_action", payload.action_id)
    if resource is not None:
        acl = (
            await session.execute(
                select(ResourceACL).where(
                    ResourceACL.resource_id == resource.id,
                    ResourceACL.subject_type == payload.subject_type,
                    ResourceACL.subject_id == payload.subject_id,
                )
            )
        ).scalar_one_or_none()
        caps = ["run"] if payload.can_run else []
        if acl is None:
            session.add(
                ResourceACL(
                    resource_id=resource.id,
                    subject_type=payload.subject_type,
                    subject_id=payload.subject_id,
                    capabilities=caps,
                )
            )
        else:
            acl.capabilities = caps
    version = await bump_permission_version(session)
    await session.commit()
    return {"ok": True, "permission_version": version}
