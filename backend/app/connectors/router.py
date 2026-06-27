import uuid
import time
from datetime import datetime
from typing import Any
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from app.audit.logger import log_event
from app.connectors.csv_upload import infer_csv_schema, load_csv_into_staging
from app.connectors.parquet_upload import store_uploaded_parquet
from app.connectors.postgres import PostgresConnector
from app.connectors.rest_api import fetch_rest_endpoint
from app.data.models import DataSource, Dataset, DatasetColumn, StreamCheckpoint, StreamSource, StreamSubscription
from app.deps import CurrentUserDep, SessionDep
from app.jobs import service as jobs_service
from app.permissions.enforcement import bump_permission_version
from app.permissions.secrets import create_secret, get_secret
from app.platform.models import ConnectorSyncRun, ConnectorTestResult
from app.platform.service import record_lineage, register_dataset_version, upsert_resource

router = APIRouter(prefix="/connectors", tags=["connectors"])


class PostgresConnIn(BaseModel):
    name: str
    host: str
    port: int = 5432
    database: str
    username: str
    password: str
    ssl_mode: str = "prefer"
    schemas: list[str] = ["public"]
    allowed_tables: list[str] | None = None
    ai_policy: str = "local_only"


class RestConnIn(BaseModel):
    name: str
    dataset_name: str
    config: dict[str, Any]
    ai_policy: str = "cloud_allowed"


class ConnectorDatasetOut(BaseModel):
    id: str
    name: str
    table_name: str
    row_count: int | None
    execution_engine: str
    ai_policy: str


class ConnectorJobOut(BaseModel):
    id: str
    job_type: str
    status: str
    error: str | None
    created_at: str
    finished_at: str | None


class ConnectorOut(BaseModel):
    id: str
    name: str
    source_type: str
    status: str
    owner_id: str | None
    created_at: str
    updated_at: str
    config: dict[str, Any]
    datasets: list[ConnectorDatasetOut]
    latest_job: ConnectorJobOut | None
    supported_actions: list[str]


class SyncRunOut(BaseModel):
    id: str
    source_id: str | None
    job_id: str | None
    status: str
    idempotency_key: str | None
    logs: list
    created_at: str
    finished_at: str | None


class ConnectorTestResultOut(BaseModel):
    id: str
    source_id: str
    status: str
    detail: str | None
    latency_ms: int | None
    created_at: str


class StreamSourceIn(BaseModel):
    name: str
    stream_type: str = "kafka"
    topic: str
    key_format: str | None = None
    value_format: str = "json"
    config: dict[str, Any] = {}


class StreamSourceOut(BaseModel):
    id: str
    data_source_id: str | None
    name: str
    stream_type: str
    topic: str
    key_format: str | None
    value_format: str
    config: dict[str, Any]
    status: str
    created_at: str
    updated_at: str


class StreamSubscriptionIn(BaseModel):
    name: str
    dataset_id: uuid.UUID | None = None
    mode: str = "append"
    schema_contract: dict[str, Any] = {}


class StreamSubscriptionOut(BaseModel):
    id: str
    stream_source_id: str
    dataset_id: str | None
    name: str
    mode: str
    checkpoint: dict
    schema_contract: dict
    status: str
    created_at: str
    updated_at: str


class StreamCheckpointIn(BaseModel):
    partition_key: str = "0"
    offset_value: str
    watermark: datetime | None = None
    details: dict[str, Any] = {}


class CsvPreviewOut(BaseModel):
    encoding: str
    columns: list[dict[str, Any]]
    sample_rows: list[dict[str, Any]]
    column_count: int
    wide_file: bool


def _safe_connector_config(source: DataSource) -> dict[str, Any]:
    hidden = {"password", "token", "api_key", "secret", "auth"}
    return {
        k: ("***" if k.lower() in hidden else v)
        for k, v in (source.connection_config or {}).items()
    }


def _connector_actions(source: DataSource) -> list[str]:
    if source.source_type == "postgres":
        return ["discover_schema"]
    return []


def _stream_source_out(row: StreamSource) -> StreamSourceOut:
    hidden = {"password", "token", "api_key", "secret", "sasl_password"}
    return StreamSourceOut(
        id=str(row.id),
        data_source_id=str(row.data_source_id) if row.data_source_id else None,
        name=row.name,
        stream_type=row.stream_type,
        topic=row.topic,
        key_format=row.key_format,
        value_format=row.value_format,
        config={k: ("***" if k.lower() in hidden else v) for k, v in (row.config or {}).items()},
        status=row.status,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _stream_subscription_out(row: StreamSubscription) -> StreamSubscriptionOut:
    return StreamSubscriptionOut(
        id=str(row.id),
        stream_source_id=str(row.stream_source_id),
        dataset_id=str(row.dataset_id) if row.dataset_id else None,
        name=row.name,
        mode=row.mode,
        checkpoint=row.checkpoint or {},
        schema_contract=row.schema_contract or {},
        status=row.status,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _cleanup_staged_table(schema: str | None, table: str | None) -> None:
    if not schema or not table:
        return
    try:
        from sqlalchemy import create_engine, text

        from app.config import get_settings
        from app.util.identifiers import assert_safe_ident

        assert_safe_ident(schema)
        assert_safe_ident(table)
        engine = create_engine(get_settings().sync_database_url)
        with engine.begin() as conn:
            conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{table}"'))
    except Exception:
        pass


def _cleanup_storage_uri(uri: str | None) -> None:
    if not uri:
        return
    try:
        from app.storage.fs import get_fs

        fs = get_fs(uri)
        if fs.exists(uri):
            fs.rm(uri)
    except Exception:
        pass


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(session: SessionDep, user: CurrentUserDep) -> list[ConnectorOut]:
    sources = list((await session.execute(
        select(DataSource)
        .where(DataSource.owner_id == user.id)
        .order_by(DataSource.updated_at.desc(), DataSource.created_at.desc())
    )).scalars().all())
    if not sources:
        return []

    source_ids = [s.id for s in sources]
    datasets = list((await session.execute(
        select(Dataset).where(Dataset.source_id.in_(source_ids)).order_by(Dataset.created_at.desc())
    )).scalars().all())
    datasets_by_source: dict[uuid.UUID, list[Dataset]] = {}
    for ds in datasets:
        if ds.source_id:
            datasets_by_source.setdefault(ds.source_id, []).append(ds)

    from app.jobs.models import Job
    jobs = list((await session.execute(
        select(Job)
        .where(Job.resource_type == "data_source", Job.resource_id.in_([str(sid) for sid in source_ids]))
        .order_by(Job.created_at.desc())
    )).scalars().all())
    latest_job_by_source: dict[str, Job] = {}
    for job in jobs:
        if job.resource_id and job.resource_id not in latest_job_by_source:
            latest_job_by_source[job.resource_id] = job

    return [
        ConnectorOut(
            id=str(source.id),
            name=source.name,
            source_type=source.source_type,
            status=source.status or "unknown",
            owner_id=str(source.owner_id) if source.owner_id else None,
            created_at=source.created_at.isoformat(),
            updated_at=source.updated_at.isoformat(),
            config=_safe_connector_config(source),
            datasets=[
                ConnectorDatasetOut(
                    id=str(ds.id),
                    name=ds.name,
                    table_name=ds.table_name,
                    row_count=ds.row_count,
                    execution_engine=ds.execution_engine,
                    ai_policy=ds.ai_policy,
                )
                for ds in datasets_by_source.get(source.id, [])
            ],
            latest_job=(
                ConnectorJobOut(
                    id=str(job.id),
                    job_type=job.job_type,
                    status=job.status,
                    error=job.error,
                    created_at=job.created_at.isoformat(),
                    finished_at=job.finished_at.isoformat() if job.finished_at else None,
                )
                if (job := latest_job_by_source.get(str(source.id))) else None
            ),
            supported_actions=_connector_actions(source),
        )
        for source in sources
    ]


@router.post("/{source_id}/sync")
async def sync_connector(source_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    source = await session.get(DataSource, source_id)
    if source is None or source.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connector not found")
    if source.source_type != "postgres":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"sync is not supported for {source.source_type} connectors yet")

    existing_dataset = (await session.execute(
        select(Dataset).where(Dataset.source_id == source.id).limit(1)
    )).scalar_one_or_none()
    ai_policy = existing_dataset.ai_policy if existing_dataset else "local_only"

    source.status = "discovering"
    job = await jobs_service.enqueue(
        session,
        user=user,
        job_type="postgres_discover",
        input={
            "source_id": str(source.id),
            "owner_id": str(user.id),
            "ai_policy": ai_policy,
            "name": source.name,
        },
        resource_type="data_source",
        resource_id=str(source.id),
        idempotency_key=f"postgres_discover:{source.id}:{source.updated_at.isoformat()}",
    )
    session.add(ConnectorSyncRun(source_id=source.id, job_id=job.id, status="queued", idempotency_key=job.idempotency_key, logs=[{"message": "sync queued"}]))
    await log_event(
        session,
        user=user,
        event_type="CONNECTOR_SYNCED",
        resource_type="data_source",
        resource_id=str(source.id),
        input_summary={"action": "discover_schema"},
        output_summary={"job_id": str(job.id)},
    )
    await session.commit()
    return {"source_id": str(source.id), "job_id": str(job.id)}


@router.get("/{source_id}/sync-runs", response_model=list[SyncRunOut])
async def list_sync_runs(source_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[SyncRunOut]:
    source = await session.get(DataSource, source_id)
    if source is None or source.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connector not found")
    rows = (await session.execute(
        select(ConnectorSyncRun).where(ConnectorSyncRun.source_id == source_id).order_by(ConnectorSyncRun.created_at.desc())
    )).scalars().all()
    return [
        SyncRunOut(
            id=str(r.id),
            source_id=str(r.source_id) if r.source_id else None,
            job_id=str(r.job_id) if r.job_id else None,
            status=r.status,
            idempotency_key=r.idempotency_key,
            logs=r.logs or [],
            created_at=r.created_at.isoformat(),
            finished_at=r.finished_at.isoformat() if r.finished_at else None,
        )
        for r in rows
    ]


def _test_result_out(row: ConnectorTestResult) -> ConnectorTestResultOut:
    return ConnectorTestResultOut(
        id=str(row.id),
        source_id=str(row.source_id),
        status=row.status,
        detail=row.detail,
        latency_ms=row.latency_ms,
        created_at=row.created_at.isoformat(),
    )


@router.get("/{source_id}/test-results", response_model=list[ConnectorTestResultOut])
async def list_connector_test_results(source_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[ConnectorTestResultOut]:
    source = await session.get(DataSource, source_id)
    if source is None or source.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connector not found")
    rows = (
        await session.execute(
            select(ConnectorTestResult).where(ConnectorTestResult.source_id == source_id).order_by(ConnectorTestResult.created_at.desc()).limit(50)
        )
    ).scalars().all()
    return [_test_result_out(row) for row in rows]


@router.post("/{source_id}/test", response_model=ConnectorTestResultOut)
async def test_saved_connector(source_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> ConnectorTestResultOut:
    source = await session.get(DataSource, source_id)
    if source is None or source.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connector not found")
    start = time.perf_counter()
    status_value = "ok"
    detail = "connection ok"
    try:
        if source.source_type == "postgres":
            cfg = dict(source.connection_config or {})
            if cfg.get("managed"):
                detail = "managed postgres source (local database)"
            else:
                if source.secret_ref:
                    cfg["password"] = await get_secret(session, uuid.UUID(source.secret_ref))
                conn = PostgresConnector(cfg)
                conn.test_connection()
        else:
            status_value = "unsupported"
            detail = f"connection test is not implemented for {source.source_type}"
    except Exception as e:
        status_value = "error"
        detail = str(e)
    row = ConnectorTestResult(source_id=source.id, status=status_value, detail=detail, latency_ms=int((time.perf_counter() - start) * 1000))
    session.add(row)
    await session.commit()
    return _test_result_out(row)


@router.get("/streams", response_model=list[StreamSourceOut])
async def list_stream_sources(session: SessionDep, user: CurrentUserDep) -> list[StreamSourceOut]:
    rows = (
        await session.execute(
            select(StreamSource).where(StreamSource.owner_id == user.id).order_by(StreamSource.updated_at.desc())
        )
    ).scalars().all()
    return [_stream_source_out(row) for row in rows]


@router.post("/streams", response_model=StreamSourceOut, status_code=201)
async def create_stream_source(payload: StreamSourceIn, session: SessionDep, user: CurrentUserDep) -> StreamSourceOut:
    if payload.stream_type not in {"kafka", "redpanda", "kinesis", "webhook"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "stream_type must be kafka, redpanda, kinesis, or webhook")
    source = DataSource(
        name=payload.name,
        source_type=f"stream:{payload.stream_type}",
        connection_config={"topic": payload.topic, **(payload.config or {})},
        status="disabled",
        owner_id=user.id,
    )
    session.add(source)
    await session.flush()
    stream = StreamSource(
        data_source_id=source.id,
        name=payload.name,
        stream_type=payload.stream_type,
        topic=payload.topic,
        key_format=payload.key_format,
        value_format=payload.value_format,
        config=payload.config or {},
        status="disabled",
        owner_id=user.id,
    )
    session.add(stream)
    await session.flush()
    await upsert_resource(
        session,
        resource_type="data_source",
        object_id=source.id,
        name=source.name,
        owner_user_id=user.id,
        metadata={"source_type": source.source_type, "stream_source_id": str(stream.id), "topic": stream.topic},
    )
    await log_event(
        session,
        user=user,
        event_type="STREAM_SOURCE_CREATED",
        resource_type="stream_source",
        resource_id=str(stream.id),
        input_summary={"stream_type": stream.stream_type, "topic": stream.topic},
    )
    await session.commit()
    return _stream_source_out(stream)


@router.get("/streams/{stream_id}/subscriptions", response_model=list[StreamSubscriptionOut])
async def list_stream_subscriptions(stream_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[StreamSubscriptionOut]:
    stream = await session.get(StreamSource, stream_id)
    if stream is None or stream.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "stream source not found")
    rows = (
        await session.execute(
            select(StreamSubscription).where(StreamSubscription.stream_source_id == stream.id).order_by(StreamSubscription.created_at.desc())
        )
    ).scalars().all()
    return [_stream_subscription_out(row) for row in rows]


@router.post("/streams/{stream_id}/subscriptions", response_model=StreamSubscriptionOut, status_code=201)
async def create_stream_subscription(
    stream_id: uuid.UUID,
    payload: StreamSubscriptionIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> StreamSubscriptionOut:
    stream = await session.get(StreamSource, stream_id)
    if stream is None or stream.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "stream source not found")
    if payload.dataset_id:
        dataset = await session.get(Dataset, payload.dataset_id)
        if dataset is None or dataset.owner_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    subscription = StreamSubscription(
        stream_source_id=stream.id,
        dataset_id=payload.dataset_id,
        name=payload.name,
        mode=payload.mode,
        schema_contract=payload.schema_contract or {},
        status="paused",
        owner_id=user.id,
    )
    session.add(subscription)
    await session.flush()
    await log_event(
        session,
        user=user,
        event_type="STREAM_SUBSCRIPTION_CREATED",
        resource_type="stream_subscription",
        resource_id=str(subscription.id),
        input_summary={"stream_source_id": str(stream.id), "dataset_id": str(payload.dataset_id) if payload.dataset_id else None},
    )
    await session.commit()
    return _stream_subscription_out(subscription)


@router.post("/streams/subscriptions/{subscription_id}/checkpoint", response_model=StreamSubscriptionOut)
async def update_stream_checkpoint(
    subscription_id: uuid.UUID,
    payload: StreamCheckpointIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> StreamSubscriptionOut:
    subscription = await session.get(StreamSubscription, subscription_id)
    if subscription is None or subscription.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "stream subscription not found")
    row = StreamCheckpoint(
        subscription_id=subscription.id,
        partition_key=payload.partition_key,
        offset_value=payload.offset_value,
        watermark=payload.watermark,
        details=payload.details or {},
    )
    session.add(row)
    subscription.checkpoint = {
        **(subscription.checkpoint or {}),
        payload.partition_key: {
            "offset": payload.offset_value,
            "watermark": payload.watermark.isoformat() if payload.watermark else None,
            "updated_at": datetime.utcnow().isoformat(),
        },
    }
    subscription.updated_at = datetime.utcnow()
    await session.commit()
    return _stream_subscription_out(subscription)


@router.post("/streams/subscriptions/{subscription_id}/poll", response_model=StreamSubscriptionOut)
async def poll_stream_subscription(subscription_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> StreamSubscriptionOut:
    subscription = await session.get(StreamSubscription, subscription_id)
    if subscription is None or subscription.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "stream subscription not found")
    stream = await session.get(StreamSource, subscription.stream_source_id)
    if stream is None or stream.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "stream source not found")
    if stream.status != "enabled":
        raise HTTPException(status.HTTP_409_CONFLICT, "stream adapter is disabled; configure and enable a supported adapter before polling")
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, f"{stream.stream_type} polling adapter is not configured")


@router.post("/postgres/test")
async def postgres_test(payload: PostgresConnIn, _: CurrentUserDep) -> dict:
    conn = PostgresConnector(payload.model_dump())
    try:
        return conn.test_connection()
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"connection failed: {e}")


@router.post("/csv/preview", response_model=CsvPreviewOut)
async def preview_csv_schema(
    _: CurrentUserDep,
    file: UploadFile = File(...),
    encoding: str | None = Form(None),
) -> CsvPreviewOut:
    file_bytes = await file.read()
    try:
        preview = infer_csv_schema(file_bytes, encoding=encoding)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"schema inference failed: {e}")
    return CsvPreviewOut(**preview)


@router.post("/postgres")
async def create_postgres_connector(payload: PostgresConnIn, session: SessionDep, user: CurrentUserDep) -> dict:
    """Quick test + register the DataSource synchronously, then enqueue
    schema discovery as a background job. The endpoint returns immediately
    with `{source_id, job_id}`; the frontend polls /jobs/{job_id} for
    completion. Per modifcation.md §3.3 + plan v0.6.
    """
    cfg = payload.model_dump()
    conn = PostgresConnector(cfg)
    try:
        conn.test_connection()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"connection failed: {e}")

    secret_id = await create_secret(session, payload.password)

    source = DataSource(
        name=payload.name,
        source_type="postgres",
        connection_config={k: v for k, v in cfg.items() if k != "password"},
        secret_ref=str(secret_id),
        status="discovering",
        owner_id=user.id,
    )
    session.add(source)
    await session.flush()
    source_resource = await upsert_resource(
        session,
        resource_type="data_source",
        object_id=source.id,
        name=source.name,
        owner_user_id=user.id,
        metadata={"source_type": "postgres", "host": payload.host, "database": payload.database},
    )

    job = await jobs_service.enqueue(
        session, user=user, job_type="postgres_discover",
        input={
            "source_id": str(source.id),
            "owner_id": str(user.id),
            "ai_policy": payload.ai_policy,
            "name": payload.name,
        },
        resource_type="data_source", resource_id=str(source.id),
    )

    await log_event(
        session, user=user, event_type="CONNECTOR_CREATED",
        resource_type="data_source", resource_id=str(source.id),
        input_summary={"type": "postgres", "host": payload.host, "database": payload.database},
        output_summary={"job_id": str(job.id)},
    )
    await session.commit()
    return {"source_id": str(source.id), "job_id": str(job.id)}


@router.post("/csv")
async def upload_csv(
    session: SessionDep,
    user: CurrentUserDep,
    file: UploadFile = File(...),
    dataset_name: str = Form(...),
    ai_policy: str = Form("local_only"),
    encoding: str | None = Form(None),
) -> dict:
    file_bytes = await file.read()
    dataset_id = uuid.uuid4()

    try:
        result = load_csv_into_staging(file_bytes, dataset_name, dataset_id, encoding=encoding)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"csv load failed: {e}")

    source = DataSource(
        name=f"csv:{dataset_name}",
        source_type="csv",
        connection_config={"filename": file.filename},
        status="ok",
        owner_id=user.id,
    )
    session.add(source)
    await session.flush()
    source_resource = await upsert_resource(
        session,
        resource_type="data_source",
        object_id=source.id,
        name=source.name,
        owner_user_id=user.id,
        metadata={"source_type": "csv", "filename": file.filename},
    )

    ds = Dataset(
        id=dataset_id,
        source_id=source.id,
        name=dataset_name,
        schema_name=result.get("schema_name", "mf_datasets"),
        table_name=result["table_name"],
        row_count=result["row_count"],
        ai_policy=ai_policy,
        storage_uri=result.get("storage_uri"),
        high_water_mark=result.get("high_water_mark"),
        owner_id=user.id,
    )
    session.add(ds)
    await session.flush()
    for c in result["columns"]:
        session.add(DatasetColumn(
            dataset_id=ds.id, name=c["name"], data_type=c["type"], sample_values=c["sample"],
        ))
    dataset_resource = await upsert_resource(
        session,
        resource_type="dataset",
        object_id=ds.id,
        name=ds.name,
        owner_user_id=user.id,
        metadata={"schema_name": ds.schema_name, "table_name": ds.table_name, "storage_uri": ds.storage_uri, "encoding": result.get("encoding")},
    )

    job = await jobs_service.enqueue(
        session, user=user, job_type="csv_profile",
        input={"dataset_id": str(ds.id), "schema": ds.schema_name, "table_name": result["table_name"]},
        resource_type="dataset", resource_id=str(ds.id),
    )
    sync_run = ConnectorSyncRun(source_id=source.id, job_id=job.id, status="succeeded", logs=[{"message": "csv uploaded"}])
    session.add(sync_run)
    await session.flush()
    version = await register_dataset_version(
        session,
        dataset=ds,
        storage_uri=result.get("storage_uri"),
        manifest={"file_count": result.get("file_count", 1), "source_filename": file.filename, "raw_source_type": "csv", "encoding": result.get("encoding")},
        created_by=user.id,
        created_by_job_id=job.id,
    )
    ds.current_version_id = version.id
    await record_lineage(
        session,
        source_resource_id=source_resource.id,
        target_resource_id=dataset_resource.id,
        target_version_id=version.id,
        edge_type="connector_to_dataset",
        created_by_job_id=job.id,
        metadata={"sync_run_id": str(sync_run.id)},
    )

    await bump_permission_version(session)
    await log_event(
        session, user=user, event_type="CONNECTOR_CREATED",
        resource_type="data_source", resource_id=str(source.id),
        input_summary={"type": "csv", "filename": file.filename},
        output_summary={"dataset_id": str(ds.id), "row_count": result["row_count"], "profile_job_id": str(job.id)},
    )
    try:
        await session.commit()
    except Exception:
        _cleanup_staged_table(result.get("schema_name"), result.get("table_name"))
        _cleanup_storage_uri(result.get("storage_uri"))
        raise
    return {"dataset_id": str(ds.id), "row_count": result["row_count"], "profile_job_id": str(job.id)}


@router.post("/rest")
async def create_rest_connector(payload: RestConnIn, session: SessionDep, user: CurrentUserDep) -> dict:
    dataset_id = uuid.uuid4()
    try:
        result = fetch_rest_endpoint(payload.config, payload.dataset_name, dataset_id)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"fetch failed: {e}")

    source = DataSource(
        name=payload.name,
        source_type="rest_api",
        connection_config={k: v for k, v in payload.config.items() if k != "auth"},
        status="ok",
        owner_id=user.id,
    )
    session.add(source)
    await session.flush()
    source_resource = await upsert_resource(
        session,
        resource_type="data_source",
        object_id=source.id,
        name=source.name,
        owner_user_id=user.id,
        metadata={"source_type": "rest_api"},
    )

    ds = Dataset(
        id=dataset_id,
        source_id=source.id,
        name=payload.dataset_name,
        schema_name=result.get("schema_name", "mf_datasets"),
        table_name=result["table_name"],
        row_count=result["row_count"],
        ai_policy=payload.ai_policy,
        owner_id=user.id,
    )
    session.add(ds)
    await session.flush()
    for c in result["columns"]:
        session.add(DatasetColumn(
            dataset_id=ds.id, name=c["name"], data_type=c["type"], sample_values=c["sample"],
        ))
    dataset_resource = await upsert_resource(
        session,
        resource_type="dataset",
        object_id=ds.id,
        name=ds.name,
        owner_user_id=user.id,
        metadata={"schema_name": ds.schema_name, "table_name": ds.table_name},
    )
    version = await register_dataset_version(
        session,
        dataset=ds,
        manifest={"source_type": "rest_api", "config_keys": sorted(payload.config.keys())},
        created_by=user.id,
    )
    ds.current_version_id = version.id
    await record_lineage(
        session,
        source_resource_id=source_resource.id,
        target_resource_id=dataset_resource.id,
        target_version_id=version.id,
        edge_type="connector_to_dataset",
    )
    await bump_permission_version(session)
    await log_event(
        session, user=user, event_type="CONNECTOR_SYNCED",
        resource_type="data_source", resource_id=str(source.id),
        input_summary={"type": "rest_api"}, output_summary={"row_count": result["row_count"]},
    )
    try:
        await session.commit()
    except Exception:
        _cleanup_staged_table(result.get("schema_name"), result.get("table_name"))
        raise
    return {"dataset_id": str(ds.id), "row_count": result["row_count"]}


@router.post("/parquet")
async def upload_parquet(
    session: SessionDep,
    user: CurrentUserDep,
    file: UploadFile = File(...),
    dataset_name: str = Form(...),
    ai_policy: str = Form("local_only"),
) -> dict:
    """Upload a single .parquet to object storage and register as a duckdb-engine dataset."""
    file_bytes = await file.read()
    dataset_id = uuid.uuid4()
    try:
        info = store_uploaded_parquet(file_bytes, dataset_name, dataset_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"parquet upload failed: {e}")

    source = DataSource(
        name=f"parquet:{dataset_name}",
        source_type="parquet",
        connection_config={"filename": file.filename, "storage_uri": info["storage_uri"]},
        status="ok",
        owner_id=user.id,
    )
    session.add(source)
    await session.flush()
    source_resource = await upsert_resource(
        session,
        resource_type="data_source",
        object_id=source.id,
        name=source.name,
        owner_user_id=user.id,
        metadata={"source_type": "parquet", "filename": file.filename},
    )

    ds = Dataset(
        id=dataset_id,
        source_id=source.id,
        name=dataset_name,
        schema_name="public",
        table_name=info["table_name"],
        ai_policy=ai_policy,
        execution_engine="duckdb",
        storage_uri=info["storage_uri"],
        owner_id=user.id,
    )
    session.add(ds)
    await session.flush()
    for c in info["columns"]:
        session.add(DatasetColumn(dataset_id=ds.id, name=c["name"], data_type=c["type"]))
    dataset_resource = await upsert_resource(
        session,
        resource_type="dataset",
        object_id=ds.id,
        name=ds.name,
        owner_user_id=user.id,
        metadata={"storage_uri": ds.storage_uri, "execution_engine": ds.execution_engine},
    )
    version = await register_dataset_version(
        session,
        dataset=ds,
        storage_uri=info["storage_uri"],
        manifest={"file_count": 1, "source_filename": file.filename, "source_type": "parquet"},
        created_by=user.id,
    )
    ds.current_version_id = version.id
    await record_lineage(
        session,
        source_resource_id=source_resource.id,
        target_resource_id=dataset_resource.id,
        target_version_id=version.id,
        edge_type="connector_to_dataset",
    )
    await bump_permission_version(session)
    await log_event(
        session, user=user, event_type="CONNECTOR_CREATED",
        resource_type="data_source", resource_id=str(source.id),
        input_summary={"type": "parquet", "filename": file.filename},
        output_summary={"dataset_id": str(ds.id), "storage_uri": info["storage_uri"]},
    )
    try:
        await session.commit()
    except Exception:
        _cleanup_storage_uri(info.get("storage_uri"))
        raise
    return {"dataset_id": str(ds.id), "storage_uri": info["storage_uri"], "columns": len(info["columns"])}
