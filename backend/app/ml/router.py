import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.audit.logger import log_event
from app.data.models import Dataset, DatasetColumn
from app.deps import CurrentUserDep, SessionDep
from app.jobs import service as jobs_service
from app.ml.models import MLModel, MLModelVersion, TASK_TYPES
from app.permissions.enforcement import effective_capabilities_for_object
from app.platform.service import (
    get_resource_for_object,
    latest_dataset_version,
    record_lineage,
    upsert_resource,
)


router = APIRouter(prefix="/models", tags=["models"])


class ModelIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str
    description: str | None = None
    task_type: str
    model_type: str = "baseline"
    input_dataset_id: uuid.UUID
    target_column: str
    feature_columns: list[str] = Field(default_factory=list)
    workspace_parent_id: uuid.UUID | None = None


class ModelOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    name: str
    description: str | None
    task_type: str
    model_type: str
    input_dataset_id: str | None
    target_column: str
    feature_columns: list[str]
    owner_id: str | None
    current_version_id: str | None
    created_at: datetime
    updated_at: datetime


class VersionOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: str
    model_id: str
    version: int
    status: str
    training_config: dict
    training_dataset_version_id: str | None
    metrics: dict | None
    artifact_path: str | None
    artifact_manifest: dict
    approval_status: str
    promoted_by: str | None
    promoted_at: datetime | None
    job_id: str | None
    created_at: datetime
    trained_at: datetime | None


class ModelDetailOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model: ModelOut
    versions: list[VersionOut]
    latest_metrics: dict | None
    input_dataset: dict | None
    feature_metadata: list[dict]
    build_job: dict | None


def _model_out(m: MLModel) -> ModelOut:
    return ModelOut(
        id=str(m.id), name=m.name, description=m.description,
        task_type=m.task_type, model_type=m.model_type,
        input_dataset_id=str(m.input_dataset_id) if m.input_dataset_id else None,
        target_column=m.target_column, feature_columns=list(m.feature_columns or []),
        owner_id=str(m.owner_id) if m.owner_id else None,
        current_version_id=str(m.current_version_id) if m.current_version_id else None,
        created_at=m.created_at, updated_at=m.updated_at,
    )


def _version_out(v: MLModelVersion) -> VersionOut:
    return VersionOut(
        id=str(v.id), model_id=str(v.model_id), version=v.version,
        status=v.status, training_config=v.training_config or {},
        training_dataset_version_id=str(v.training_dataset_version_id) if v.training_dataset_version_id else None,
        metrics=v.metrics, artifact_path=v.artifact_path,
        artifact_manifest=v.artifact_manifest or {},
        approval_status=v.approval_status,
        promoted_by=str(v.promoted_by) if v.promoted_by else None,
        promoted_at=v.promoted_at,
        job_id=str(v.job_id) if v.job_id else None,
        created_at=v.created_at, trained_at=v.trained_at,
    )


async def _require_model_cap(session, user, model_id: uuid.UUID, capability: str) -> MLModel:
    """Load a model and enforce a central ResourceACL capability.

    Mirrors the dataset pattern in app/data/router.py: the owner always has
    access, otherwise the capability (or "manage") must be granted via the
    resource graph.
    """
    m = await session.get(MLModel, model_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "model not found")
    caps = await effective_capabilities_for_object(session, user, "model", model_id)
    if m.owner_id != user.id and not ({capability, "manage"} & caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing capability: {capability}")
    return m


async def _check_dataset(session, user, dataset_id: uuid.UUID) -> None:
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "input dataset not found")
    if ds.owner_id == user.id:
        return
    caps = await effective_capabilities_for_object(session, user, "dataset", dataset_id)
    if not (("view_data" in caps and "use_in_sql" in caps) or "manage" in caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing dataset SQL permission")


@router.get("", response_model=list[ModelOut])
async def list_models(session: SessionDep, user: CurrentUserDep) -> list[ModelOut]:
    rows = await session.execute(select(MLModel).order_by(MLModel.updated_at.desc()))
    visible: list[ModelOut] = []
    for m in rows.scalars().all():
        if m.owner_id == user.id:
            visible.append(_model_out(m))
            continue
        caps = await effective_capabilities_for_object(session, user, "model", m.id)
        if {"view_metadata", "manage"} & caps:
            visible.append(_model_out(m))
    return visible


@router.post("", response_model=ModelOut)
async def create_model(payload: ModelIn, session: SessionDep, user: CurrentUserDep) -> ModelOut:
    if payload.task_type not in TASK_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "task_type must be classification|regression")
    if not payload.feature_columns:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "feature_columns required")
    await _check_dataset(session, user, payload.input_dataset_id)
    data = payload.model_dump(exclude={"workspace_parent_id"})
    m = MLModel(**data, owner_id=user.id)
    session.add(m)
    await session.flush()
    model_resource = await upsert_resource(
        session,
        resource_type="model",
        object_id=m.id,
        name=m.name,
        owner_user_id=user.id,
        metadata={
            "task_type": m.task_type,
            "model_type": m.model_type,
            "input_dataset_id": str(m.input_dataset_id),
            "target_column": m.target_column,
        },
    )
    dataset_resource = await get_resource_for_object(session, "dataset", payload.input_dataset_id)
    input_version = await latest_dataset_version(session, payload.input_dataset_id)
    if dataset_resource:
        await record_lineage(
            session,
            source_resource_id=dataset_resource.id,
            source_version_id=input_version.id if input_version else None,
            target_resource_id=model_resource.id,
            edge_type="dataset_to_model",
            metadata={"purpose": "training_source"},
        )
    from app.workspace.service import create_linked_item
    await create_linked_item(
        session,
        user_id=user.id,
        name=m.name,
        item_type="model",
        resource_type="model",
        resource_id=m.id,
        parent_id=payload.workspace_parent_id,
    )
    await log_event(session, user=user, event_type="MODEL_EDITED", resource_type="model", resource_id=str(m.id), input_summary={"action": "create", "name": m.name})
    await session.commit()
    return _model_out(m)


@router.get("/{model_id}", response_model=ModelOut)
async def get_model(model_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> ModelOut:
    return _model_out(await _require_model_cap(session, user, model_id, "view_metadata"))


@router.get("/{model_id}/detail", response_model=ModelDetailOut)
async def get_model_detail(model_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> ModelDetailOut:
    m = await _require_model_cap(session, user, model_id, "view_metadata")
    versions_q = await session.execute(
        select(MLModelVersion).where(MLModelVersion.model_id == model_id).order_by(MLModelVersion.version.desc())
    )
    versions = list(versions_q.scalars().all())
    latest = versions[0] if versions else None
    ds = await session.get(Dataset, m.input_dataset_id) if m.input_dataset_id else None
    cols_q = await session.execute(select(DatasetColumn).where(DatasetColumn.dataset_id == m.input_dataset_id).order_by(DatasetColumn.name))
    columns = list(cols_q.scalars().all())
    selected = set(m.feature_columns or []) | ({m.target_column} if m.target_column else set())
    feature_metadata = [
        {
            "name": c.name,
            "data_type": c.data_type,
            "description": c.description,
            "sample_values": c.sample_values,
            "role": "target" if c.name == m.target_column else "feature" if c.name in selected else "available",
        }
        for c in columns
    ]
    build_job = None
    if latest and latest.job_id:
        from app.jobs.models import Job
        job = await session.get(Job, latest.job_id)
        if job:
            build_job = {
                "id": str(job.id),
                "status": job.status,
                "job_type": job.job_type,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            }
    return ModelDetailOut(
        model=_model_out(m),
        versions=[_version_out(v) for v in versions],
        latest_metrics=latest.metrics if latest else None,
        input_dataset={
            "id": str(ds.id),
            "name": ds.name,
            "schema_name": ds.schema_name,
            "table_name": ds.table_name,
            "row_count": ds.row_count,
        } if ds else None,
        feature_metadata=feature_metadata,
        build_job=build_job,
    )


@router.delete("/{model_id}")
async def delete_model(model_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    m = await _require_model_cap(session, user, model_id, "manage")
    await session.delete(m)
    await log_event(session, user=user, event_type="MODEL_EDITED", resource_type="model", resource_id=str(model_id), input_summary={"action": "delete"})
    await session.commit()
    return {"ok": True}


@router.post("/{model_id}/train", response_model=VersionOut)
async def train_model(model_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> VersionOut:
    m = await _require_model_cap(session, user, model_id, "run")
    await _check_dataset(session, user, m.input_dataset_id)
    input_version = await latest_dataset_version(session, m.input_dataset_id) if m.input_dataset_id else None
    max_q = await session.execute(select(func.max(MLModelVersion.version)).where(MLModelVersion.model_id == model_id))
    next_version = int(max_q.scalar() or 0) + 1
    v = MLModelVersion(
        model_id=m.id,
        version=next_version,
        status="queued",
        training_config={
            "feature_columns": list(m.feature_columns or []),
            "target_column": m.target_column,
            "model_type": m.model_type,
        },
        training_dataset_version_id=input_version.id if input_version else None,
        approval_status="draft",
    )
    session.add(v)
    await session.flush()
    job = await jobs_service.enqueue(
        session, user=user, job_type="model_train",
        input={"model_id": str(m.id), "version_id": str(v.id), "user_id": str(user.id)},
        resource_type="model", resource_id=str(m.id),
    )
    v.job_id = job.id
    dataset_resource = await get_resource_for_object(session, "dataset", m.input_dataset_id) if m.input_dataset_id else None
    model_resource = await get_resource_for_object(session, "model", m.id)
    if dataset_resource and model_resource:
        await record_lineage(
            session,
            source_resource_id=dataset_resource.id,
            source_version_id=input_version.id if input_version else None,
            target_resource_id=model_resource.id,
            target_version_id=v.id,
            edge_type="dataset_to_model_version",
            created_by_job_id=job.id,
            metadata={"version": next_version, "target_column": m.target_column},
        )
    await log_event(session, user=user, event_type="MODEL_TRAIN_STARTED", resource_type="model", resource_id=str(m.id), input_summary={"version": next_version})
    await session.commit()
    return _version_out(v)


@router.get("/{model_id}/versions", response_model=list[VersionOut])
async def list_versions(model_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[VersionOut]:
    await _require_model_cap(session, user, model_id, "view_metadata")
    rows = await session.execute(
        select(MLModelVersion).where(MLModelVersion.model_id == model_id).order_by(MLModelVersion.version.desc())
    )
    return [_version_out(v) for v in rows.scalars().all()]


@router.post("/{model_id}/versions/{version_id}/predict-preview")
async def predict_preview(model_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    await _require_model_cap(session, user, model_id, "run")
    v = await session.get(MLModelVersion, version_id)
    if v is None or v.model_id != model_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "model version not found")
    return {"status": v.status, "metrics": v.metrics or {}, "artifact_path": v.artifact_path}


@router.post("/{model_id}/versions/{version_id}/promote", response_model=ModelOut)
async def promote_model_version(model_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> ModelOut:
    m = await _require_model_cap(session, user, model_id, "manage")
    v = await session.get(MLModelVersion, version_id)
    if v is None or v.model_id != model_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "model version not found")
    if v.status not in {"ready", "promoted"} or not v.artifact_path:
        raise HTTPException(status.HTTP_409_CONFLICT, "only trained model versions with artifacts can be promoted")
    if m.current_version_id and m.current_version_id != v.id:
        current = await session.get(MLModelVersion, m.current_version_id)
        if current:
            current.status = "ready"
    m.current_version_id = v.id
    m.updated_at = datetime.utcnow()
    v.status = "promoted"
    v.approval_status = "approved"
    v.promoted_by = user.id
    v.promoted_at = datetime.utcnow()
    await log_event(
        session,
        user=user,
        event_type="MODEL_VERSION_PROMOTED",
        resource_type="model",
        resource_id=str(m.id),
        input_summary={"version_id": str(v.id), "version": v.version},
    )
    await session.commit()
    return _model_out(m)


@router.post("/{model_id}/rollback", response_model=ModelOut)
async def rollback_model_version(model_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> ModelOut:
    m = await _require_model_cap(session, user, model_id, "manage")
    rows = (
        await session.execute(
            select(MLModelVersion)
            .where(MLModelVersion.model_id == model_id, MLModelVersion.status.in_(["ready", "promoted"]))
            .order_by(MLModelVersion.version.desc())
        )
    ).scalars().all()
    candidates = [v for v in rows if v.id != m.current_version_id and v.artifact_path]
    if not candidates:
        raise HTTPException(status.HTTP_409_CONFLICT, "no previous ready model version exists")
    previous = candidates[0]
    if m.current_version_id:
        current = await session.get(MLModelVersion, m.current_version_id)
        if current:
            current.status = "ready"
    m.current_version_id = previous.id
    m.updated_at = datetime.utcnow()
    previous.status = "promoted"
    previous.approval_status = "approved"
    previous.promoted_by = user.id
    previous.promoted_at = datetime.utcnow()
    await log_event(
        session,
        user=user,
        event_type="MODEL_VERSION_ROLLED_BACK",
        resource_type="model",
        resource_id=str(m.id),
        input_summary={"version_id": str(previous.id), "version": previous.version},
    )
    await session.commit()
    return _model_out(m)
