"""HTTP surface for the visual pipeline builder."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.ai import gateway
from app.audit.logger import log_event
from app.data.models import DatasetColumn
from app.deps import CurrentUserDep, SessionDep
from app.execution.sql_validator import SqlValidationError
from app.ontology.models import OntologyObject, OntologyRelationship
from app.permissions.enforcement import PermissionDenied, require_object_capability
from app.pipelines import service
from app.pipelines.ai import AIPipelineError, generate_pipeline_graph
from app.pipelines.compiler import PipelineCompileError
from app.pipelines.models import Pipeline, PipelineEdge, PipelineNode
from app.platform.models import ResourceVersion
from app.platform.service import get_resource_for_object, register_resource_version, upsert_resource
from app.pipelines.schemas import (
    AiGenerateIn,
    AiGenerateOut,
    CreatePipelineIn,
    EdgeOut,
    NodeOut,
    PipelineDetail,
    PipelineSummary,
    PreviewIn,
    PreviewOut,
    RunOut,
    UpdatePipelineIn,
)


router = APIRouter(prefix="/pipelines", tags=["pipelines"])


# --- helpers ---------------------------------------------------------------


def _summary(p: Pipeline) -> PipelineSummary:
    return PipelineSummary(
        id=str(p.id),
        name=p.name,
        description=p.description,
        owner_id=str(p.owner_id) if p.owner_id else None,
        ai_policy=p.ai_policy,
        output_dataset_id=str(p.output_dataset_id) if p.output_dataset_id else None,
        materialization_type=p.materialization_type or "view",
        materialized_at=p.materialized_at,
        materialized_rows=p.materialized_rows,
        last_run_at=p.last_run_at,
        last_run_status=p.last_run_status,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _node_out(n: PipelineNode) -> NodeOut:
    return NodeOut(
        id=str(n.id),
        node_type=n.node_type,
        position=n.position or {},
        config=n.config or {},
    )


def _edge_out(e: PipelineEdge) -> EdgeOut:
    return EdgeOut(
        id=str(e.id),
        source_node_id=str(e.source_node_id),
        target_node_id=str(e.target_node_id),
        target_handle=e.target_handle,
    )


async def _detail(session, p: Pipeline) -> PipelineDetail:
    n_q = await session.execute(select(PipelineNode).where(PipelineNode.pipeline_id == p.id))
    e_q = await session.execute(select(PipelineEdge).where(PipelineEdge.pipeline_id == p.id))
    return PipelineDetail(
        **_summary(p).model_dump(),
        graph=p.graph or {},
        nodes=[_node_out(n) for n in n_q.scalars().all()],
        edges=[_edge_out(e) for e in e_q.scalars().all()],
        last_run_error=p.last_run_error,
    )


async def _pipeline_snapshot(session, p: Pipeline) -> dict:
    detail = await _detail(session, p)
    return detail.model_dump(mode="json")


async def _register_pipeline_version(session, p: Pipeline, user_id: uuid.UUID, branch_name: str, kind: str) -> None:
    resource = await get_resource_for_object(session, "pipeline", p.id)
    if resource is None:
        return
    await register_resource_version(
        session,
        resource=resource,
        created_by=user_id,
        branch_name=branch_name or "main",
        manifest={"kind": kind, "branch_name": branch_name or "main", "pipeline": await _pipeline_snapshot(session, p)},
    )


async def _register_pipeline_detail_version(
    session,
    p: Pipeline,
    detail: PipelineDetail,
    user_id: uuid.UUID,
    branch_name: str,
    kind: str,
) -> None:
    resource = await get_resource_for_object(session, "pipeline", p.id)
    if resource is None:
        return
    await register_resource_version(
        session,
        resource=resource,
        created_by=user_id,
        branch_name=branch_name or "main",
        manifest={"kind": kind, "branch_name": branch_name or "main", "pipeline": detail.model_dump(mode="json")},
    )


async def _latest_pipeline_branch_detail(session, p: Pipeline, branch_name: str) -> PipelineDetail | None:
    resource = await get_resource_for_object(session, "pipeline", p.id)
    if resource is None:
        return None
    version = (await session.execute(
        select(ResourceVersion)
        .where(ResourceVersion.resource_id == resource.id, ResourceVersion.branch_name == branch_name)
        .order_by(ResourceVersion.version_number.desc())
        .limit(1)
    )).scalar_one_or_none()
    manifest = version.manifest if version else None
    payload = (manifest or {}).get("pipeline")
    return PipelineDetail(**payload) if payload else None


async def _branch_update_detail(session, p: Pipeline, payload: UpdatePipelineIn) -> PipelineDetail:
    base = await _latest_pipeline_branch_detail(session, p, payload.branch_name)
    if base is None:
        base = await _detail(session, p)
    data = base.model_dump()
    if payload.name is not None:
        data["name"] = payload.name
    if payload.description is not None:
        data["description"] = payload.description
    if payload.graph is not None:
        data["graph"] = payload.graph
    if payload.materialization_type is not None:
        data["materialization_type"] = payload.materialization_type
    if payload.nodes is not None:
        data["nodes"] = [
            NodeOut(id=n.id, node_type=n.node_type, position=n.position, config=n.config).model_dump()
            for n in payload.nodes
        ]
    if payload.edges is not None:
        data["edges"] = [
            EdgeOut(id=e.id, source_node_id=e.source_node_id, target_node_id=e.target_node_id, target_handle=e.target_handle).model_dump()
            for e in payload.edges
        ]
    data["updated_at"] = datetime.utcnow()
    return PipelineDetail(**data)


async def _require_owner(session, user, pipeline_id: uuid.UUID) -> Pipeline:
    p = await session.get(Pipeline, pipeline_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pipeline not found")
    if p.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not the pipeline owner")
    return p


# --- CRUD ------------------------------------------------------------------


@router.get("", response_model=list[PipelineSummary])
async def list_pipelines(session: SessionDep, user: CurrentUserDep) -> list[PipelineSummary]:
    rows = await service.list_pipelines(session, user.id)
    return [_summary(r) for r in rows]


@router.post("", response_model=PipelineDetail)
async def create_pipeline(
    payload: CreatePipelineIn, session: SessionDep, user: CurrentUserDep
) -> PipelineDetail:
    p = Pipeline(name=payload.name, description=payload.description, owner_id=user.id, graph={})
    session.add(p)
    await session.flush()
    await upsert_resource(
        session,
        resource_type="pipeline",
        object_id=p.id,
        name=p.name,
        owner_user_id=user.id,
        metadata={"materialization_type": p.materialization_type},
    )
    if payload.branch_name != "main":
        await _register_pipeline_version(session, p, user.id, payload.branch_name, "pipeline_created")
    from app.workspace.service import create_linked_item
    await create_linked_item(
        session,
        user_id=user.id,
        name=p.name,
        item_type="pipeline",
        resource_type="pipeline",
        resource_id=p.id,
        parent_id=payload.workspace_parent_id,
    )
    await log_event(
        session, user=user, event_type="PIPELINE_EDITED",
        resource_type="pipeline", resource_id=str(p.id),
        input_summary={"action": "create", "name": p.name},
    )
    await session.commit()
    return await _detail(session, p)


@router.get("/{pipeline_id}", response_model=PipelineDetail)
async def get_pipeline(pipeline_id: uuid.UUID, session: SessionDep, user: CurrentUserDep, branch_name: str | None = Query(default=None)) -> PipelineDetail:
    p = await _require_owner(session, user, pipeline_id)
    if branch_name and branch_name != "main":
        branch_detail = await _latest_pipeline_branch_detail(session, p, branch_name)
        if branch_detail is not None:
            return branch_detail
    return await _detail(session, p)


@router.patch("/{pipeline_id}", response_model=PipelineDetail)
async def update_pipeline(
    pipeline_id: uuid.UUID,
    payload: UpdatePipelineIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> PipelineDetail:
    p = await _require_owner(session, user, pipeline_id)
    if payload.branch_name != "main":
        detail = await _branch_update_detail(session, p, payload)
        await _register_pipeline_detail_version(session, p, detail, user.id, payload.branch_name, "pipeline_updated")
        await log_event(
            session, user=user, event_type="PIPELINE_EDITED",
            resource_type="pipeline", resource_id=str(p.id),
            input_summary={"action": "update", "branch_name": payload.branch_name},
        )
        await session.commit()
        return detail
    if payload.name is not None:
        p.name = payload.name
    if payload.description is not None:
        p.description = payload.description
    if payload.graph is not None:
        p.graph = payload.graph
    if payload.nodes is not None or payload.edges is not None:
        existing = await _detail(session, p)
        nodes = [n.model_dump() for n in payload.nodes] if payload.nodes is not None else [n.model_dump() for n in existing.nodes]
        edges = [e.model_dump() for e in payload.edges] if payload.edges is not None else [e.model_dump() for e in existing.edges]
        try:
            await service.replace_graph(session, p, nodes=nodes, edges=edges)
        except service.PipelineServiceError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))
    if payload.materialization_type is not None:
        p.materialization_type = payload.materialization_type
    p.updated_at = datetime.utcnow()
    await upsert_resource(session, resource_type="pipeline", object_id=p.id, name=p.name, owner_user_id=p.owner_id, metadata={"materialization_type": p.materialization_type})
    await _register_pipeline_version(session, p, user.id, payload.branch_name, "pipeline_updated")
    await log_event(
        session, user=user, event_type="PIPELINE_EDITED",
        resource_type="pipeline", resource_id=str(p.id),
        input_summary={"action": "update", "branch_name": payload.branch_name},
    )
    await session.commit()
    return await _detail(session, p)


@router.delete("/{pipeline_id}")
async def delete_pipeline(
    pipeline_id: uuid.UUID, session: SessionDep, user: CurrentUserDep
) -> dict:
    p = await _require_owner(session, user, pipeline_id)
    await session.delete(p)
    await log_event(
        session, user=user, event_type="PIPELINE_EDITED",
        resource_type="pipeline", resource_id=str(pipeline_id),
        input_summary={"action": "delete"},
    )
    await session.commit()
    return {"ok": True}


# --- preview / run ---------------------------------------------------------


@router.post("/{pipeline_id}/preview", response_model=PreviewOut)
async def preview_pipeline(
    pipeline_id: uuid.UUID,
    payload: PreviewIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> PreviewOut:
    p = await _require_owner(session, user, pipeline_id)
    try:
        if payload.branch_name != "main":
            branch_detail = await _latest_pipeline_branch_detail(session, p, payload.branch_name)
            if branch_detail is None:
                raise PipelineCompileError(f"branch not found: {payload.branch_name}")
            result = await service.preview_graph(
                session,
                user,
                nodes=[node.model_dump() for node in branch_detail.nodes],
                edges=[edge.model_dump() for edge in branch_detail.edges],
                limit=payload.limit,
            )
        else:
            result = await service.preview(session, user, p, limit=payload.limit)
    except PipelineCompileError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"compile error: {e}")
    except SqlValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"sql invalid: {e}")
    except service.PipelineServiceError as e:
        status_code = status.HTTP_403_FORBIDDEN if "missing" in str(e).lower() else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code, str(e))
    return PreviewOut(columns=result["columns"], rows=result["rows"], sql=result["sql"])


@router.post("/{pipeline_id}/run", response_model=RunOut)
async def run_pipeline(
    pipeline_id: uuid.UUID, session: SessionDep, user: CurrentUserDep
) -> RunOut:
    p = await _require_owner(session, user, pipeline_id)
    n_q = await session.execute(select(PipelineNode).where(PipelineNode.pipeline_id == p.id))
    nodes = list(n_q.scalars().all())
    
    mode = service._materialization_mode(p, nodes)
    if mode in {"table", "parquet"}:
        from app.jobs.service import enqueue
        job = await enqueue(
            session,
            user=user,
            job_type="run_pipeline",
            input={"pipeline_id": str(p.id), "user_id": str(user.id)},
            resource_type="pipeline",
            resource_id=str(p.id),
        )
        await log_event(
            session, user=user, event_type="PIPELINE_RUN_QUEUED",
            resource_type="pipeline", resource_id=str(p.id),
            output_summary={"status": "queued", "job_id": str(job.id)},
        )
        await session.commit()
        return RunOut(status="queued", job_id=str(job.id))

    try:
        result = await service.run(session, user.id, p)
    except service.PipelineServiceError as e:
        status_code = status.HTTP_403_FORBIDDEN if "missing" in str(e).lower() else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code, str(e))
    except SqlValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"sql invalid: {e}")
    await log_event(
        session, user=user, event_type="PIPELINE_RUN",
        resource_type="pipeline", resource_id=str(p.id),
        output_summary={"status": result.get("status"), "view": result.get("view_name")},
    )
    await session.commit()
    return RunOut(**result)


@router.get("/{pipeline_id}/nodes/{node_id}/schema")
async def node_schema(
    pipeline_id: uuid.UUID,
    node_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    p = await _require_owner(session, user, pipeline_id)
    node = await session.get(PipelineNode, node_id)
    if node is None or node.pipeline_id != p.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "node not found")
    if node.node_type == "source":
        ds_id = (node.config or {}).get("dataset_id")
        if not ds_id:
            return {"node_id": str(node_id), "columns": []}
        try:
            await require_object_capability(session, user, "dataset", uuid.UUID(str(ds_id)), "view_metadata")
        except PermissionDenied as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
        rows = await session.execute(
            select(DatasetColumn).where(DatasetColumn.dataset_id == uuid.UUID(str(ds_id))).order_by(DatasetColumn.name)
        )
        return {
            "node_id": str(node_id),
            "dataset_id": str(ds_id),
            "columns": [{"name": c.name, "data_type": c.data_type, "description": c.description} for c in rows.scalars().all()],
        }
    try:
        result = await service.preview(session, user, p, limit=1)
        return {"node_id": str(node_id), "columns": [{"name": c, "data_type": None, "description": None} for c in result["columns"]]}
    except Exception as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))


@router.get("/{pipeline_id}/nodes/{node_id}/preview")
async def node_preview(
    pipeline_id: uuid.UUID,
    node_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
    limit: int = 50,
) -> dict:
    p = await _require_owner(session, user, pipeline_id)
    node = await session.get(PipelineNode, node_id)
    if node is None or node.pipeline_id != p.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "node not found")
    try:
        result = await service.preview(session, user, p, limit=max(1, min(limit, 200)))
        return {"node_id": str(node_id), **result}
    except Exception as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))


@router.post("/{pipeline_id}/validate")
async def validate_pipeline(
    pipeline_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    p = await _require_owner(session, user, pipeline_id)
    n_q = await session.execute(select(PipelineNode).where(PipelineNode.pipeline_id == p.id))
    e_q = await session.execute(select(PipelineEdge).where(PipelineEdge.pipeline_id == p.id))
    nodes = list(n_q.scalars().all())
    edges = list(e_q.scalars().all())
    warnings: list[dict] = []
    errors: list[dict] = []

    if not nodes:
        errors.append({"code": "empty_pipeline", "message": "Add at least one dataset or transform node."})
    if not any(n.node_type == "output" for n in nodes):
        warnings.append({"code": "missing_output", "message": "Add an output node before deploying this pipeline."})
    for node in nodes:
        cfg = node.config or {}
        if node.node_type == "filter" and not cfg.get("where"):
            warnings.append({"code": "empty_filter", "node_id": str(node.id), "message": "Filter node has no SQL boolean expression."})
        if node.node_type == "join" and (not cfg.get("left_keys") or not cfg.get("right_keys")):
            warnings.append({"code": "missing_join_keys", "node_id": str(node.id), "message": "Join node is missing left or right keys."})
        if node.node_type == "select" and cfg.get("columns") == []:
            warnings.append({"code": "empty_select", "node_id": str(node.id), "message": "Select node has no selected columns."})
    connected = {str(e.source_node_id) for e in edges} | {str(e.target_node_id) for e in edges}
    for node in nodes:
        if len(nodes) > 1 and str(node.id) not in connected:
            warnings.append({"code": "unconnected_node", "node_id": str(node.id), "message": f"{node.node_type} node is not connected."})

    try:
        preview = await service.preview(session, user, p, limit=5)
        if not preview.get("rows"):
            warnings.append({"code": "preview_empty", "message": "The current graph preview returned no rows."})
        if preview.get("columns") and "ltv" not in {str(c).lower() for c in preview["columns"]}:
            warnings.append({"code": "ltv_column_missing", "message": "Preview does not include an LTV column. Tests expecting ltv will fail."})
    except Exception as e:
        errors.append({"code": "compile_or_preview_failed", "message": str(e)})
    return {"status": "error" if errors else "ok", "warnings": warnings, "errors": errors}


# --- join suggestion --------------------------------------------------------


@router.get("/_suggest/join")
async def suggest_join(
    left_dataset_id: uuid.UUID,
    right_dataset_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,  # noqa: ARG001 — auth only
) -> dict:
    """Suggest a join from the ontology when both datasets are typed.

    Returns the best matching ontology relationship, if any, plus the
    suggested join_type and key pair. Used by the canvas the moment an
    edge is drawn between two source nodes.
    """
    for dataset_id in (left_dataset_id, right_dataset_id):
        try:
            await require_object_capability(session, user, "dataset", dataset_id, "view_metadata")
        except PermissionDenied as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    objs_q = await session.execute(
        select(OntologyObject).where(OntologyObject.dataset_id.in_([left_dataset_id, right_dataset_id]))
    )
    objs = list(objs_q.scalars().all())
    by_ds = {o.dataset_id: o for o in objs}
    left_obj = by_ds.get(left_dataset_id)
    right_obj = by_ds.get(right_dataset_id)
    if not left_obj or not right_obj:
        return {"suggestion": None}

    rel_q = await session.execute(
        select(OntologyRelationship).where(
            ((OntologyRelationship.source_type == left_obj.type_name) & (OntologyRelationship.target_type == right_obj.type_name))
            | ((OntologyRelationship.source_type == right_obj.type_name) & (OntologyRelationship.target_type == left_obj.type_name))
        )
    )
    rel = rel_q.scalars().first()
    if rel is None:
        return {"suggestion": None}

    # Normalize so left_keys belong to the left input.
    if rel.source_type == left_obj.type_name:
        left_keys, right_keys = [rel.source_key], [rel.target_key]
    else:
        left_keys, right_keys = [rel.target_key], [rel.source_key]
    join_type = "inner" if rel.cardinality in ("one_to_one", "many_to_one") else "left"
    return {
        "suggestion": {
            "relationship_id": str(rel.id),
            "relationship_name": rel.name,
            "cardinality": rel.cardinality,
            "join_type": join_type,
            "left_keys": left_keys,
            "right_keys": right_keys,
            "source_type": rel.source_type,
            "target_type": rel.target_type,
        }
    }


# --- AI generation ----------------------------------------------------------


@router.post("/ai-generate", response_model=AiGenerateOut)
async def ai_generate(
    payload: AiGenerateIn, session: SessionDep, user: CurrentUserDep
) -> AiGenerateOut:
    model = payload.model or gateway.default_model_for(payload.provider)
    try:
        result = await generate_pipeline_graph(
            session=session,
            user=user,
            prompt=payload.prompt,
            provider=payload.provider,
            model=model,
            dataset_ids=payload.dataset_ids,
        )
    except gateway.AIPolicyError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    except AIPipelineError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    await log_event(
        session, user=user, event_type="AI_PROVIDER_USED",
        resource_type="pipeline_ai_generate", provider=payload.provider,
        input_summary={"prompt": payload.prompt, "model": model},
        output_summary={"name": result["name"], "node_count": len(result["nodes"])},
    )
    await session.commit()
    return AiGenerateOut(
        name=result["name"],
        description=result["description"],
        nodes=[NodeOut(**n) for n in result["nodes"]],
        edges=[EdgeOut(**e) for e in result["edges"]],
        provider=payload.provider,
        model=model,
    )
