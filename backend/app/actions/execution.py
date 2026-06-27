"""Shared action execution paths for direct triggers and approval decisions."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.actions.registry import WORKFLOWS, get_workflow
from app.audit.logger import log_event
from app.auth.models import User
from app.config import get_settings
from app.ontology.models import ActionRun, OntologyAction
from app.permissions.enforcement import PermissionDenied
from app.platform.service import get_resource_for_object, record_lineage


def sync_run_workflow(workflow_key: str, user: User, params: dict[str, Any]) -> dict[str, Any]:
    wf = get_workflow(workflow_key)
    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as session:
        try:
            result = wf["fn"](session, user, params)
            session.commit()
        except Exception:
            session.rollback()
            raise
    return result if isinstance(result, dict) else {"result": result}


async def execute_action_run(
    session: AsyncSession,
    *,
    user: User,
    action: OntologyAction,
    action_run: ActionRun,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Execute an already-authorized action run without committing."""

    action_run.status = "running"
    action_resource = await get_resource_for_object(session, "ontology_action", action.id)

    if action.object_type:
        from app.ontology.writeback import execute_writeback

        try:
            result = await execute_writeback(session, user, action, params)
            action_run.status = "succeeded"
            action_run.output = result
            action_run.before_state = result.get("old_values") if isinstance(result, dict) else None
            action_run.after_state = result.get("new_values") if isinstance(result, dict) else {"result": result}
            action_run.writeback_destination = action.object_type
            action_run.finished_at = datetime.utcnow()
            if action_resource:
                await record_lineage(
                    session,
                    source_resource_id=action_resource.id,
                    target_resource_id=None,
                    edge_type="action_to_writeback",
                    metadata={
                        "action_run_id": str(action_run.id),
                        "object_type": action.object_type,
                        "writeback_destination": action.object_type,
                    },
                )
            await log_event(
                session,
                user=user,
                event_type="ACTION_TRIGGERED",
                resource_type="action",
                resource_id=str(action.id),
                input_summary={"action": action.name, "params": params, "writeback": True},
                output_summary=result,
            )
            return {"status": "succeeded", "action_run_id": str(action_run.id), "output": result}
        except PermissionDenied as e:
            action_run.status = "failed"
            action_run.error = str(e)
            action_run.finished_at = datetime.utcnow()
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
        except ValueError as e:
            err_msg = str(e)
            action_run.status = "failed"
            action_run.error = err_msg
            action_run.finished_at = datetime.utcnow()
            if err_msg.startswith("Validation failed:"):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"detail": err_msg}) from e
            raise HTTPException(status.HTTP_400_BAD_REQUEST, err_msg) from e
        except Exception as e:  # noqa: BLE001
            await log_event(
                session,
                user=user,
                event_type="ACTION_TRIGGERED",
                resource_type="action",
                resource_id=str(action.id),
                input_summary={"action": action.name, "params": params, "writeback": True},
                output_summary={"error": str(e)},
            )
            action_run.status = "failed"
            action_run.error = str(e)
            action_run.finished_at = datetime.utcnow()
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)) from e

    if action.workflow_key not in WORKFLOWS:
        action_run.status = "failed"
        action_run.error = f"workflow not loaded: {action.workflow_key}"
        action_run.finished_at = datetime.utcnow()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"workflow not loaded: {action.workflow_key}")

    wf = get_workflow(action.workflow_key)
    if wf["sync"]:
        try:
            result = sync_run_workflow(action.workflow_key, user, params)
        except Exception as e:  # noqa: BLE001
            await log_event(
                session,
                user=user,
                event_type="ACTION_TRIGGERED",
                resource_type="action",
                resource_id=str(action.id),
                input_summary={"action": action.name, "params": params},
                output_summary={"error": str(e)},
            )
            action_run.status = "failed"
            action_run.error = str(e)
            action_run.finished_at = datetime.utcnow()
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)) from e
        action_run.status = "succeeded"
        action_run.output = result
        action_run.finished_at = datetime.utcnow()
        if action_resource:
            await record_lineage(
                session,
                source_resource_id=action_resource.id,
                target_resource_id=None,
                edge_type="action_to_workflow",
                metadata={"action_run_id": str(action_run.id), "workflow_key": action.workflow_key},
            )
        await log_event(
            session,
            user=user,
            event_type="ACTION_TRIGGERED",
            resource_type="action",
            resource_id=str(action.id),
            input_summary={"action": action.name, "params": params},
            output_summary={"sync": True},
        )
        return {"status": "succeeded", "action_run_id": str(action_run.id), "output": result}

    from app.jobs import service as jobs_service

    job = await jobs_service.enqueue(
        session,
        user=user,
        job_type="run_workflow",
        input={"workflow_key": action.workflow_key, "params": params, "user_id": str(user.id)},
        resource_type="action",
        resource_id=str(action.id),
        idempotency_key=action_run.idempotency_key,
    )
    action_run.status = "queued"
    action_run.output = {"job_id": str(job.id)}
    await log_event(
        session,
        user=user,
        event_type="ACTION_TRIGGERED",
        resource_type="action",
        resource_id=str(action.id),
        input_summary={"action": action.name, "params": params},
        output_summary={"job_id": str(job.id)},
    )
    return {"status": "queued", "job_id": str(job.id), "action_run_id": str(action_run.id)}
