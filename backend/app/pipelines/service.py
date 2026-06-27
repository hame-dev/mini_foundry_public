"""Pipeline CRUD + run.

``run`` compiles the graph, validates the result is a read-only SELECT,
materializes it as a Postgres VIEW in the ``mf_pipelines`` schema, and
registers a corresponding logical Dataset row so the catalog / dashboards /
notebooks see the pipeline output as a first-class dataset.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import joblib
import pandas as pd
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.config import get_settings
from app.data.models import Dataset, DatasetColumn
from app.governed_query.service import governed_query, prepare_governed_sql
from app.permissions.enforcement import PermissionDenied
from app.dashboards.models import SavedQuery
from app.execution.sql_validator import validate_sql
from app.permissions.enforcement import effective_capabilities_for_object
from app.platform.models import PipelineVersion
from app.platform.service import (
    add_build_input,
    add_build_output,
    create_build_run,
    finish_build_run,
    get_resource_for_object,
    latest_dataset_version,
    record_lineage,
    register_dataset_version,
    upsert_resource,
)
from app.pipelines.compiler import (
    CompiledPipeline,
    PipelineCompileError,
    compile_pipeline,
)
from app.pipelines.models import Pipeline, PipelineEdge, PipelineNode
from app.ml.models import MLModelVersion


MANAGED_SCHEMA = "mf_pipelines"


# Most-restrictive first.
_POLICY_ORDER = {"local_only": 3, "metadata_only": 2, "cloud_allowed": 1}


class PipelineServiceError(RuntimeError):
    pass


# -------- Load helpers ------------------------------------------------------


async def list_pipelines(session: AsyncSession, user_id: uuid.UUID) -> list[Pipeline]:
    # v1: owner sees their pipelines; admins see all via existing role checks elsewhere
    q = await session.execute(
        select(Pipeline).where(Pipeline.owner_id == user_id).order_by(Pipeline.updated_at.desc())
    )
    return list(q.scalars().all())


async def get_pipeline_with_graph(
    session: AsyncSession, pipeline_id: uuid.UUID
) -> tuple[Pipeline, list[PipelineNode], list[PipelineEdge]] | None:
    pipeline = await session.get(Pipeline, pipeline_id)
    if pipeline is None:
        return None
    n_q = await session.execute(
        select(PipelineNode).where(PipelineNode.pipeline_id == pipeline_id).order_by(PipelineNode.created_at)
    )
    e_q = await session.execute(
        select(PipelineEdge).where(PipelineEdge.pipeline_id == pipeline_id).order_by(PipelineEdge.created_at)
    )
    return pipeline, list(n_q.scalars().all()), list(e_q.scalars().all())


async def replace_graph(
    session: AsyncSession,
    pipeline: Pipeline,
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[PipelineNode], list[PipelineEdge]]:
    """Replace nodes/edges for a pipeline atomically."""
    await session.execute(delete(PipelineEdge).where(PipelineEdge.pipeline_id == pipeline.id))
    await session.execute(delete(PipelineNode).where(PipelineNode.pipeline_id == pipeline.id))
    await session.flush()

    # Map client-supplied node ids to UUIDs we persist.
    id_map: dict[str, uuid.UUID] = {}
    n_rows: list[PipelineNode] = []
    for n in nodes:
        try:
            persistent_id = uuid.UUID(n["id"])
        except (KeyError, ValueError):
            persistent_id = uuid.uuid4()
        id_map[n["id"]] = persistent_id
        row = PipelineNode(
            id=persistent_id,
            pipeline_id=pipeline.id,
            node_type=n["node_type"],
            position=n.get("position") or {},
            config=n.get("config") or {},
        )
        session.add(row)
        n_rows.append(row)

    e_rows: list[PipelineEdge] = []
    for e in edges:
        try:
            eid = uuid.UUID(e["id"])
        except (KeyError, ValueError):
            eid = uuid.uuid4()
        src = id_map.get(e["source_node_id"])
        tgt = id_map.get(e["target_node_id"])
        if src is None or tgt is None:
            raise PipelineServiceError(f"edge references missing node: {e}")
        row = PipelineEdge(
            id=eid,
            pipeline_id=pipeline.id,
            source_node_id=src,
            target_node_id=tgt,
            target_handle=e.get("target_handle") or "in",
        )
        session.add(row)
        e_rows.append(row)
    await session.flush()
    return n_rows, e_rows


# -------- Compile + run -----------------------------------------------------


async def _load_dataset_bundle(
    session: AsyncSession, dataset_ids: list[uuid.UUID]
) -> tuple[list[Dataset], dict[uuid.UUID, list[DatasetColumn]]]:
    if not dataset_ids:
        return [], {}
    ds_q = await session.execute(select(Dataset).where(Dataset.id.in_(dataset_ids)))
    datasets = list(ds_q.scalars().all())
    col_q = await session.execute(
        select(DatasetColumn).where(DatasetColumn.dataset_id.in_(dataset_ids)).order_by(DatasetColumn.name)
    )
    by_ds: dict[uuid.UUID, list[DatasetColumn]] = {}
    for c in col_q.scalars().all():
        by_ds.setdefault(c.dataset_id, []).append(c)
    return datasets, by_ds


def _collect_source_dataset_ids(nodes: list[dict[str, Any]]) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for n in nodes:
        if n.get("node_type") == "source":
            ds_id = (n.get("config") or {}).get("dataset_id")
            if ds_id:
                try:
                    out.append(uuid.UUID(str(ds_id)))
                except ValueError:
                    pass
    # dedupe preserving order
    seen: set[uuid.UUID] = set()
    deduped: list[uuid.UUID] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            deduped.append(x)
    return deduped


def _strictest_policy(datasets: list[Dataset]) -> str:
    if not datasets:
        return "local_only"
    return max(datasets, key=lambda d: _POLICY_ORDER.get(d.ai_policy, 0)).ai_policy


async def compile_for_pipeline(
    session: AsyncSession, pipeline: Pipeline
) -> tuple[CompiledPipeline, list[Dataset]]:
    n_q = await session.execute(select(PipelineNode).where(PipelineNode.pipeline_id == pipeline.id))
    e_q = await session.execute(select(PipelineEdge).where(PipelineEdge.pipeline_id == pipeline.id))
    nodes_rows = list(n_q.scalars().all())
    edges_rows = list(e_q.scalars().all())

    nodes = [
        {
            "id": str(n.id),
            "node_type": n.node_type,
            "position": n.position,
            "config": n.config,
        }
        for n in nodes_rows
    ]
    edges = [
        {
            "id": str(e.id),
            "source_node_id": str(e.source_node_id),
            "target_node_id": str(e.target_node_id),
            "target_handle": e.target_handle,
        }
        for e in edges_rows
    ]

    source_ds_ids = _collect_source_dataset_ids(nodes)
    datasets, columns_by_id = await _load_dataset_bundle(session, source_ds_ids)
    compiled = compile_pipeline(
        nodes=nodes,
        edges=edges,
        datasets=datasets,
        dataset_columns_by_id=columns_by_id,
    )
    return compiled, datasets


async def _check_inputs_readable(
    session: AsyncSession, user_id: uuid.UUID, datasets: list[Dataset]
) -> None:
    user = await session.get(User, user_id)
    for ds in datasets:
        if ds.owner_id == user_id:
            continue
        caps = await effective_capabilities_for_object(session, user, "dataset", ds.id)
        if not (("view_data" in caps and "use_in_sql" in caps) or "manage" in caps):
            raise PipelineServiceError(
                f"missing can_use_in_sql on dataset {ds.name} ({ds.id})"
            )


def _view_name(pipeline_id: uuid.UUID) -> str:
    # Stable, schema-safe identifier.
    return f"mf_pipeline_{str(pipeline_id).replace('-', '_')}"


def _execute_ddl(statements: list[str]) -> None:
    """One-off DDL escape hatch: only used for CREATE/REPLACE/DROP VIEW.

    The read-only SQL runner cannot do DDL — pipeline materialization is the
    single place we step outside that contract.
    """
    settings = get_settings()
    engine = create_engine(settings.sync_database_url)
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def _trained_model_config(nodes: list[PipelineNode]) -> dict[str, Any] | None:
    for n in nodes:
        if n.node_type == "trained_model":
            return n.config or {}
    return None


def _materialize_predictions(
    *,
    sql: str,
    model_version: MLModelVersion,
    prediction_column: str,
    schema: str,
    table: str,
) -> None:
    if not model_version.artifact_path:
        raise PipelineServiceError("selected model version has no artifact")
    artifact = joblib.load(model_version.artifact_path)
    pipe = artifact["pipeline"]
    features = artifact["features"]
    settings = get_settings()
    engine = create_engine(settings.sync_database_url)
    df = pd.read_sql(text(f"SELECT * FROM ({sql}) _pipeline"), engine)
    missing = [c for c in features if c not in df.columns]
    if missing:
        raise PipelineServiceError(f"model features missing from pipeline input: {', '.join(missing)}")
    df[prediction_column] = pipe.predict(df[features])
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.execute(text(f'DROP VIEW IF EXISTS "{schema}"."{table}"'))
        conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{table}"'))
    df.to_sql(table, engine, schema=schema, if_exists="replace", index=False)


async def preview(
    session: AsyncSession, user: User, pipeline: Pipeline, *, limit: int = 100
) -> dict[str, Any]:
    compiled, datasets = await compile_for_pipeline(session, pipeline)
    return await _preview_compiled_governed(session, user, compiled, datasets, limit=limit)


async def preview_graph(
    session: AsyncSession,
    user: User,
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    limit: int = 100,
) -> dict[str, Any]:
    source_ds_ids = _collect_source_dataset_ids(nodes)
    datasets, columns_by_id = await _load_dataset_bundle(session, source_ds_ids)
    compiled = compile_pipeline(
        nodes=nodes,
        edges=edges,
        datasets=datasets,
        dataset_columns_by_id=columns_by_id,
    )
    return await _preview_compiled_governed(session, user, compiled, datasets, limit=limit)


async def _preview_compiled_governed(
    session: AsyncSession,
    user: User,
    compiled: CompiledPipeline,
    datasets: list[Dataset],
    *,
    limit: int = 100,
) -> dict[str, Any]:
    validate_sql(compiled.sql)
    try:
        await _check_inputs_readable(session, user.id, datasets)
    except PermissionDenied as exc:
        raise PipelineServiceError(str(exc)) from exc
    settings = get_settings()
    bounded_limit = max(1, min(limit, settings.sql_row_limit))
    final_sql = f"SELECT * FROM ({compiled.sql}) _pipeline LIMIT {bounded_limit}"
    try:
        result = await governed_query(
            session,
            user,
            final_sql,
            dataset_ids=compiled.dataset_ids,
            capability="use_in_sql",
            audit_resource_type="pipeline_preview",
        )
    except PermissionDenied as exc:
        raise PipelineServiceError(str(exc)) from exc
    return {"columns": result["columns"], "rows": result["rows"], "sql": compiled.sql}


async def run(
    session: AsyncSession, user_id: uuid.UUID, pipeline: Pipeline
) -> dict[str, Any]:
    """Compile, validate, permission-check, materialize as VIEW, register Dataset."""
    build = None
    try:
        compiled, datasets = await compile_for_pipeline(session, pipeline)
    except PipelineCompileError as e:
        pipeline.last_run_status = "error"
        pipeline.last_run_error = str(e)
        pipeline.last_run_at = datetime.utcnow()
        return {"status": "error", "error": str(e)}

    # Read-only check & permission check
    validate_sql(compiled.sql)
    await _check_inputs_readable(session, user_id, datasets)
    user = await session.get(User, user_id)
    if user is None:
        raise PipelineServiceError("user not found")
    try:
        governed_sql = await prepare_governed_sql(
            session,
            user,
            compiled.sql,
            dataset_ids=compiled.dataset_ids,
            capability="use_in_sql",
        )
    except PermissionDenied as exc:
        raise PipelineServiceError(str(exc)) from exc
    pipeline.ai_policy = _strictest_policy(datasets)
    pipeline_version_number = await _next_pipeline_version_number(session, pipeline.id)
    pipeline_version = PipelineVersion(
        pipeline_id=pipeline.id,
        version_number=pipeline_version_number,
        graph=pipeline.graph or {},
        compiled_plan={"sql": compiled.sql, "dataset_ids": [str(x) for x in compiled.dataset_ids]},
        created_by=user_id,
    )
    session.add(pipeline_version)
    await session.flush()
    build = await create_build_run(
        session,
        pipeline_id=pipeline.id,
        created_by=user_id,
        trigger_type="manual",
        idempotency_key=f"{pipeline.id}:{pipeline_version_number}:{hash(compiled.sql)}",
        compiled_plan={"sql": compiled.sql, "dataset_ids": [str(x) for x in compiled.dataset_ids]},
    )
    # Pin each source to the immutable version captured at build time. Reads that
    # flow through governed_query (e.g. duckdb sources) resolve to this version's
    # storage; postgres logical sources are recorded but read live.
    pin_map: dict[uuid.UUID, uuid.UUID] = {}
    for source_ds in datasets:
        build_input = await add_build_input(session, build.id, source_ds)
        if build_input.dataset_version_id is not None:
            pin_map[source_ds.id] = build_input.dataset_version_id
    if pin_map:
        from app.audit.logger import log_event

        await log_event(
            session,
            user=user,
            event_type="BUILD_INPUTS_PINNED",
            resource_type="pipeline",
            resource_id=str(pipeline.id),
            input_summary={
                "build_run_id": str(build.id),
                "pinned_versions": {str(k): str(v) for k, v in pin_map.items()},
            },
        )

    n_q = await session.execute(select(PipelineNode).where(PipelineNode.pipeline_id == pipeline.id))
    node_list_all = list(n_q.scalars().all())
    model_cfg = _trained_model_config(node_list_all)
    view = _view_name(pipeline.id)
    qualified = f'"{MANAGED_SCHEMA}"."{view}"'
    try:
        if model_cfg and model_cfg.get("version_id"):
            version = await session.get(MLModelVersion, uuid.UUID(str(model_cfg["version_id"])))
            if version is None or version.status != "ready":
                raise PipelineServiceError("selected model version is not ready")
            _materialize_predictions(
                sql=governed_sql,
                model_version=version,
                prediction_column=model_cfg.get("prediction_column") or "prediction",
                schema=MANAGED_SCHEMA,
                table=view,
            )
        else:
            mode = _materialization_mode(pipeline, node_list_all)
            if mode == "parquet":
                # will be handled after ds upsert below
                pass
            elif mode == "table":
                ddl = [
                    f'CREATE SCHEMA IF NOT EXISTS "{MANAGED_SCHEMA}"',
                    f"DROP VIEW IF EXISTS {qualified}",
                    f"DROP TABLE IF EXISTS {qualified}",
                    f"CREATE TABLE {qualified} AS\n{governed_sql}",
                ]
                _execute_ddl(ddl)
            else:
                ddl = [
                    f'CREATE SCHEMA IF NOT EXISTS "{MANAGED_SCHEMA}"',
                    f"DROP TABLE IF EXISTS {qualified}",
                    f"DROP VIEW IF EXISTS {qualified}",
                    f"CREATE VIEW {qualified} AS\n{governed_sql}",
                ]
                _execute_ddl(ddl)
    except Exception as e:  # noqa: BLE001
        pipeline.last_run_status = "error"
        pipeline.last_run_error = f"materialize failed: {e}"
        pipeline.last_run_at = datetime.utcnow()
        if build:
            await finish_build_run(session, build, status="failed", error_summary=str(e))
        return {"status": "error", "error": str(e)}

    # Upsert SavedQuery
    sq: SavedQuery | None = None
    if pipeline.output_saved_query_id is not None:
        sq = await session.get(SavedQuery, pipeline.output_saved_query_id)
    if sq is None:
        sq = SavedQuery(
            name=f"pipeline:{pipeline.name}",
            sql=governed_sql,
            dataset_ids=compiled.dataset_ids,
            owner_id=user_id,
        )
        session.add(sq)
        await session.flush()
        pipeline.output_saved_query_id = sq.id
    else:
        sq.name = f"pipeline:{pipeline.name}"
        sq.sql = governed_sql
        sq.dataset_ids = compiled.dataset_ids

    # Upsert Dataset row pointing at the view
    inherited_markings = set()
    for src in datasets:
        inherited_markings.update(src.security_markings or [])
    markings_list = list(inherited_markings)

    n_q2 = await session.execute(select(PipelineNode).where(PipelineNode.pipeline_id == pipeline.id))
    current_mode = _materialization_mode(pipeline, list(n_q2.scalars().all()))

    ds: Dataset | None = None
    if pipeline.output_dataset_id is not None:
        ds = await session.get(Dataset, pipeline.output_dataset_id)
    if ds is None:
        ds = Dataset(
            name=compiled.output_name or pipeline.name,
            description=compiled.output_description or pipeline.description,
            schema_name=MANAGED_SCHEMA,
            table_name=view,
            ai_policy=pipeline.ai_policy,
            execution_engine="postgres",
            security_markings=markings_list,
            owner_id=user_id,
        )
        session.add(ds)
        await session.flush()
        pipeline.output_dataset_id = ds.id
    else:
        ds.name = compiled.output_name or pipeline.name
        ds.description = compiled.output_description or pipeline.description
        ds.schema_name = MANAGED_SCHEMA
        ds.table_name = view
        ds.ai_policy = pipeline.ai_policy
        ds.security_markings = markings_list
    output_resource = await upsert_resource(
        session,
        resource_type="dataset",
        object_id=ds.id,
        name=ds.name,
        owner_user_id=user_id,
        metadata={"schema_name": ds.schema_name, "table_name": ds.table_name, "pipeline_id": str(pipeline.id)},
    )

    # Parquet materialization: write to object storage, update dataset to duckdb engine
    if current_mode == "parquet" and not (model_cfg and model_cfg.get("version_id")):
        try:
            storage_uri = _materialize_parquet(governed_sql, pipeline, ds)
            ds.execution_engine = "duckdb"
            ds.storage_uri = storage_uri
            ds.schema_name = MANAGED_SCHEMA
        except Exception as e:  # noqa: BLE001
            pipeline.last_run_status = "error"
            pipeline.last_run_error = f"parquet write failed: {e}"
            pipeline.last_run_at = datetime.utcnow()
            if build:
                await finish_build_run(session, build, status="failed", error_summary=str(e))
            return {"status": "error", "error": str(e)}

    # Refresh column rows from the compiled output_columns
    await session.execute(delete(DatasetColumn).where(DatasetColumn.dataset_id == ds.id))
    for col in compiled.output_columns:
        session.add(DatasetColumn(dataset_id=ds.id, name=col, data_type=None))

    # Best-effort row_count + profile (skip on failure)
    row_count = 0
    try:
        settings = get_settings()
        engine = create_engine(settings.sync_database_url)
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {qualified}")).scalar() or 0
            row_count = int(count)
            ds.row_count = row_count
    except Exception:  # noqa: BLE001
        pass

    # Run expectations check
    from app.pipelines.expectations import validate_expectations_async, ExpectationFailedError
    try:
        await validate_expectations_async(session, ds.id)
    except ExpectationFailedError as e:
        pipeline.last_run_status = "error"
        pipeline.last_run_error = str(e)
        pipeline.last_run_at = datetime.utcnow()
        if build:
            await finish_build_run(session, build, status="failed", error_summary=str(e))
        return {"status": "error", "error": f"Expectations failed: {e}"}

    pipeline.last_run_status = "ok"
    pipeline.last_run_error = None
    pipeline.last_run_at = datetime.utcnow()
    pipeline.updated_at = datetime.utcnow()
    pipeline.materialized_at = datetime.utcnow()
    pipeline.materialized_rows = row_count
    version = await register_dataset_version(
        session,
        dataset=ds,
        storage_uri=ds.storage_uri,
        manifest={"pipeline_id": str(pipeline.id), "compiled_sql": compiled.sql, "materialization_type": current_mode},
        created_by=user_id,
        created_by_build_id=build.id if build else None,
    )
    ds.current_version_id = version.id
    if build:
        await add_build_output(session, build.id, ds, version)
        await finish_build_run(session, build, status="succeeded")
    pipeline_resource = await upsert_resource(
        session,
        resource_type="pipeline",
        object_id=pipeline.id,
        name=pipeline.name,
        owner_user_id=user_id,
        metadata={"output_dataset_id": str(ds.id), "last_build_id": str(build.id) if build else None},
    )
    for source_ds in datasets:
        source_resource = await get_resource_for_object(session, "dataset", source_ds.id)
        source_version = await latest_dataset_version(session, source_ds.id)
        await record_lineage(
            session,
            source_resource_id=source_resource.id if source_resource else None,
            source_version_id=source_version.id if source_version else None,
            target_resource_id=output_resource.id,
            target_version_id=version.id,
            edge_type="dataset_to_dataset",
            created_by_build_id=build.id if build else None,
        )
    await record_lineage(
        session,
        source_resource_id=pipeline_resource.id,
        target_resource_id=output_resource.id,
        target_version_id=version.id,
        edge_type="pipeline_to_output",
        created_by_build_id=build.id if build else None,
    )

    return {
        "status": "ok",
        "output_dataset_id": str(ds.id),
        "output_saved_query_id": str(sq.id),
        "view_name": f"{MANAGED_SCHEMA}.{view}",
        "columns": compiled.output_columns,
        "materialization_type": current_mode,
        "materialized_rows": row_count,
        "build_run_id": str(build.id) if build else None,
        "output_dataset_version_id": str(version.id),
    }


async def _next_pipeline_version_number(session: AsyncSession, pipeline_id: uuid.UUID) -> int:
    from sqlalchemy import func
    current = (
        await session.execute(select(func.max(PipelineVersion.version_number)).where(PipelineVersion.pipeline_id == pipeline_id))
    ).scalar_one_or_none()
    return int(current or 0) + 1


def _materialization_mode(pipeline: Pipeline, nodes: list[PipelineNode]) -> str:
    """Return 'view' | 'table' | 'parquet'.

    Pipeline-level materialization_type takes precedence. Falls back to the
    legacy per-node config for backwards compatibility.
    """
    if pipeline.materialization_type and pipeline.materialization_type != "view":
        return pipeline.materialization_type
    for n in nodes:
        if n.node_type == "output":
            cfg_val = (n.config or {}).get("materialize")
            if cfg_val in ("table", "parquet"):
                return cfg_val
    return "view"


def _materialize_parquet(sql: str, pipeline: Pipeline, ds: "Dataset") -> str:
    """Execute SQL via DuckDB, write result as Parquet to MinIO, return storage_uri."""
    import duckdb
    from app.execution.duckdb_runner import _configure_httpfs
    settings = get_settings()

    object_key = f"pipeline_outputs/{pipeline.id}/{_view_name(pipeline.id)}.parquet"
    if settings.storage_backend == "s3":
        storage_uri = f"s3://{settings.s3_bucket}/{object_key}"
    else:
        storage_uri = f"/tmp/{object_key}"

    con = duckdb.connect(":memory:")
    try:
        con.execute(f"SET memory_limit='{settings.duckdb_memory_limit}'")
        _configure_httpfs(con)
        src_engine = create_engine(settings.sync_database_url)
        import pandas as pd
        df = pd.read_sql(text(sql), src_engine)
        if settings.storage_backend == "s3":
            import boto3, io
            buf = io.BytesIO()
            df.to_parquet(buf, index=False)
            buf.seek(0)
            s3 = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
            )
            s3.put_object(Bucket=settings.s3_bucket, Key=object_key, Body=buf.read())
        else:
            import os
            os.makedirs(os.path.dirname(storage_uri), exist_ok=True)
            df.to_parquet(storage_uri, index=False)
        return storage_uri
    finally:
        con.close()


def _is_table_materialization(nodes: list[PipelineNode]) -> bool:
    for n in nodes:
        if n.node_type == "output":
            return (n.config or {}).get("materialize") == "table"
    return False


def _load_dataset_bundle_sync(session, dataset_ids: list[uuid.UUID]) -> tuple[list[Dataset], dict[uuid.UUID, list[DatasetColumn]]]:
    if not dataset_ids:
        return [], {}
    datasets = session.query(Dataset).filter(Dataset.id.in_(dataset_ids)).all()
    cols = session.query(DatasetColumn).filter(DatasetColumn.dataset_id.in_(dataset_ids)).order_by(DatasetColumn.name).all()
    by_ds: dict[uuid.UUID, list[DatasetColumn]] = {}
    for c in cols:
        by_ds.setdefault(c.dataset_id, []).append(c)
    return datasets, by_ds


def compile_for_pipeline_sync(session, pipeline: Pipeline) -> tuple[CompiledPipeline, list[Dataset]]:
    nodes_rows = session.query(PipelineNode).filter(PipelineNode.pipeline_id == pipeline.id).all()
    edges_rows = session.query(PipelineEdge).filter(PipelineEdge.pipeline_id == pipeline.id).all()

    nodes = [
        {
            "id": str(n.id),
            "node_type": n.node_type,
            "position": n.position,
            "config": n.config,
        }
        for n in nodes_rows
    ]
    edges = [
        {
            "id": str(e.id),
            "source_node_id": str(e.source_node_id),
            "target_node_id": str(e.target_node_id),
            "target_handle": e.target_handle,
        }
        for e in edges_rows
    ]

    source_ds_ids = _collect_source_dataset_ids(nodes)
    datasets, columns_by_id = _load_dataset_bundle_sync(session, source_ds_ids)
    compiled = compile_pipeline(
        nodes=nodes,
        edges=edges,
        datasets=datasets,
        dataset_columns_by_id=columns_by_id,
    )
    return compiled, datasets


def run_sync(session, user_id: uuid.UUID, pipeline: Pipeline) -> dict[str, Any]:
    import time
    start_time = time.perf_counter()
    try:
        compiled, datasets = compile_for_pipeline_sync(session, pipeline)
    except PipelineCompileError as e:
        pipeline.last_run_status = "error"
        pipeline.last_run_error = str(e)
        pipeline.last_run_at = datetime.utcnow()
        session.commit()
        return {"status": "error", "error": str(e)}

    validate_sql(compiled.sql)
    pipeline.ai_policy = _strictest_policy(datasets)

    nodes_rows = session.query(PipelineNode).filter(PipelineNode.pipeline_id == pipeline.id).all()
    model_cfg = _trained_model_config(nodes_rows)
    view = _view_name(pipeline.id)
    qualified = f'"{MANAGED_SCHEMA}"."{view}"'

    try:
        if model_cfg and model_cfg.get("version_id"):
            version = session.get(MLModelVersion, uuid.UUID(str(model_cfg["version_id"])))
            if version is None or version.status != "ready":
                raise PipelineServiceError("selected model version is not ready")
            _materialize_predictions(
                sql=compiled.sql,
                model_version=version,
                prediction_column=model_cfg.get("prediction_column") or "prediction",
                schema=MANAGED_SCHEMA,
                table=view,
            )
        else:
            mode = _materialization_mode(pipeline, nodes_rows)
            if mode == "parquet":
                pass
            elif mode == "table":
                ddl = [
                    f'CREATE SCHEMA IF NOT EXISTS "{MANAGED_SCHEMA}"',
                    f"DROP VIEW IF EXISTS {qualified}",
                    f"DROP TABLE IF EXISTS {qualified}",
                    f"CREATE TABLE {qualified} AS\n{compiled.sql}",
                ]
            else:
                ddl = [
                    f'CREATE SCHEMA IF NOT EXISTS "{MANAGED_SCHEMA}"',
                    f"DROP TABLE IF EXISTS {qualified}",
                    f"DROP VIEW IF EXISTS {qualified}",
                    f"CREATE VIEW {qualified} AS\n{compiled.sql}",
                ]
            if mode != "parquet":
                _execute_ddl(ddl)
    except Exception as e:
        pipeline.last_run_status = "error"
        pipeline.last_run_error = f"materialize failed: {e}"
        pipeline.last_run_at = datetime.utcnow()
        session.commit()
        return {"status": "error", "error": str(e)}

    # Upsert SavedQuery
    sq = None
    if pipeline.output_saved_query_id is not None:
        sq = session.get(SavedQuery, pipeline.output_saved_query_id)
    if sq is None:
        sq = SavedQuery(
            name=f"pipeline:{pipeline.name}",
            sql=compiled.sql,
            dataset_ids=compiled.dataset_ids,
            owner_id=user_id,
        )
        session.add(sq)
        session.flush()
        pipeline.output_saved_query_id = sq.id
    else:
        sq.name = f"pipeline:{pipeline.name}"
        sq.sql = compiled.sql
        sq.dataset_ids = compiled.dataset_ids

    # Upsert Dataset row pointing at the view
    inherited_markings = set()
    for src in datasets:
        inherited_markings.update(src.security_markings or [])
    markings_list = list(inherited_markings)

    ds = None
    if pipeline.output_dataset_id is not None:
        ds = session.get(Dataset, pipeline.output_dataset_id)
    if ds is None:
        ds = Dataset(
            name=compiled.output_name or pipeline.name,
            description=compiled.output_description or pipeline.description,
            schema_name=MANAGED_SCHEMA,
            table_name=view,
            ai_policy=pipeline.ai_policy,
            execution_engine="postgres",
            security_markings=markings_list,
            owner_id=user_id,
        )
        session.add(ds)
        session.flush()
        pipeline.output_dataset_id = ds.id
    else:
        ds.name = compiled.output_name or pipeline.name
        ds.description = compiled.output_description or pipeline.description
        ds.schema_name = MANAGED_SCHEMA
        ds.table_name = view
        ds.ai_policy = pipeline.ai_policy
        ds.security_markings = markings_list
        ds.execution_engine = "postgres"
        ds.storage_uri = None

    current_mode = _materialization_mode(pipeline, nodes_rows)
    if current_mode == "parquet" and not (model_cfg and model_cfg.get("version_id")):
        try:
            storage_uri = _materialize_parquet(governed_sql, pipeline, ds)
            ds.execution_engine = "duckdb"
            ds.storage_uri = storage_uri
            ds.schema_name = MANAGED_SCHEMA
        except Exception as e:
            pipeline.last_run_status = "error"
            pipeline.last_run_error = f"parquet write failed: {e}"
            pipeline.last_run_at = datetime.utcnow()
            session.commit()
            return {"status": "error", "error": str(e)}

    # Refresh column rows from the compiled output_columns
    session.query(DatasetColumn).filter(DatasetColumn.dataset_id == ds.id).delete()
    for col in compiled.output_columns:
        session.add(DatasetColumn(dataset_id=ds.id, name=col, data_type=None))

    # Best-effort row_count
    row_count = 0
    try:
        settings = get_settings()
        engine = create_engine(settings.sync_database_url)
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {qualified}")).scalar() or 0
            row_count = int(count)
            ds.row_count = row_count
    except Exception:
        pass

    # Run expectations check
    from app.pipelines.expectations import validate_expectations_sync, ExpectationFailedError
    try:
        validate_expectations_sync(session, ds.id)
    except ExpectationFailedError as e:
        pipeline.last_run_status = "error"
        pipeline.last_run_error = str(e)
        pipeline.last_run_at = datetime.utcnow()
        session.commit()
        return {"status": "error", "error": f"Expectations failed: {e}"}

    pipeline.last_run_status = "ok"
    pipeline.last_run_error = None
    pipeline.last_run_at = datetime.utcnow()
    pipeline.updated_at = datetime.utcnow()
    pipeline.materialized_at = datetime.utcnow()
    pipeline.materialized_rows = row_count

    # Track usage metrics
    execution_time_ms = int((time.perf_counter() - start_time) * 1000)
    from app.governance.models import UsageMetric
    import uuid
    base_credits = 0.1
    rate = 0.0005
    compute_credits = base_credits + (execution_time_ms * rate)
    metric = UsageMetric(
        id=uuid.uuid4(),
        user_id=user_id,
        resource_type="pipeline",
        resource_id=str(pipeline.id),
        compute_credits=compute_credits,
        execution_time_ms=execution_time_ms,
        created_at=datetime.utcnow()
    )
    session.add(metric)
    session.commit()

    return {
        "status": "ok",
        "output_dataset_id": str(ds.id),
        "output_saved_query_id": str(sq.id),
        "view_name": f"{MANAGED_SCHEMA}.{view}",
        "columns": compiled.output_columns,
        "materialization_type": current_mode,
        "materialized_rows": row_count,
    }
