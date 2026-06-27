import uuid
from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.audit.logger import log_event
from app.data.catalog import get_columns, get_latest_profile, list_visible_datasets
from app.data.models import BranchTransaction, Dataset, DatasetColumn, DatasetProfile, DatasetStorageManifest, Expectation, QualityResult
from app.deps import CurrentUserDep, SessionDep
from app.permissions.enforcement import PermissionDenied, effective_capabilities_for_object, require_object_capability
from app.governed_query.service import governed_dataset_preview, governed_query
from app.pipelines.expectations import ExpectationFailedError, validate_expectations_async
from app.platform.models import DatasetSchemaVersion, DatasetVersion
from app.platform.service import get_resource_for_object, register_resource_version

QUALITY_RULE_TYPES = {"not_null", "unique", "min", "max", "pattern"}
QUALITY_SEVERITIES = {"error", "warn"}


async def _require_dataset_cap(session, user, dataset_id: uuid.UUID, capability: str) -> Dataset:
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    if ds.owner_id == user.id:
        return ds
    try:
        await require_object_capability(session, user, "dataset", dataset_id, capability)
    except PermissionDenied:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing capability: {capability}")
    return ds

router = APIRouter(prefix="/catalog", tags=["catalog"])


class DatasetOut(BaseModel):
    id: str
    name: str
    description: str | None
    source_id: str | None
    schema_name: str
    table_name: str
    row_count: int | None
    ai_policy: str
    derived_from_pipeline_id: str | None = None
    security_markings: list[str] = []
    stewards: list[str] = []
    tags: list[str] = []
    glossary_terms: list[str] = []
    created_at: datetime
    current_version_id: str | None = None


class ColumnOut(BaseModel):
    name: str
    data_type: str | None
    description: str | None
    sample_values: list | None


class DatasetDetailOut(DatasetOut):
    columns: list[ColumnOut]
    profile: dict | None
    resource_id: str | None = None


class DatasetVersionOut(BaseModel):
    id: str
    version_number: int
    schema_version_id: str | None
    storage_uri: str | None
    manifest: dict
    row_count: int | None
    file_count: int | None
    content_hash: str | None
    branch_name: str
    quality_status: str
    state: str
    created_at: datetime


class DatasetStorageManifestOut(BaseModel):
    id: str
    dataset_id: str
    dataset_version_id: str | None
    storage_uri: str | None
    manifest: dict
    file_count: int | None
    total_bytes: int | None
    content_hash: str | None
    created_at: datetime


class ClassificationConfirmIn(BaseModel):
    column_name: str
    classifications: list[str]
    sensitivity: str | None = None
    suggested_markings: list[str] = []


class SchemaDiffOut(BaseModel):
    from_version_id: str
    to_version_id: str
    added: list[dict]
    removed: list[dict]
    changed: list[dict]


class LineageNode(BaseModel):
    id: str
    type: str
    name: str
    row_count: int | None = None
    description: str | None = None


class LineageEdge(BaseModel):
    id: str
    source: str
    target: str


class LineageOut(BaseModel):
    nodes: list[LineageNode]
    edges: list[LineageEdge]


@router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(session: SessionDep, user: CurrentUserDep) -> list[DatasetOut]:
    rows = await list_visible_datasets(session, user.id)
    return [_to_out(d) for d in rows]


@router.get("/datasets/{dataset_id}", response_model=DatasetDetailOut)
async def get_dataset(dataset_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> DatasetDetailOut:
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    caps = await effective_capabilities_for_object(session, user, "dataset", dataset_id)
    if not ({"view_metadata", "manage"} & caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no metadata access")
    cols = await get_columns(session, dataset_id)
    profile = await get_latest_profile(session, dataset_id)
    await log_event(session, user=user, event_type="DATASET_VIEWED", resource_type="dataset", resource_id=str(dataset_id))
    await session.commit()
    base = _to_out(ds)
    resource = await get_resource_for_object(session, "dataset", ds.id)
    return DatasetDetailOut(
        **base.model_dump(),
        columns=[
            ColumnOut(name=c.name, data_type=c.data_type, description=c.description, sample_values=c.sample_values)
            for c in cols
        ],
        profile=profile.profile if profile else None,
        resource_id=str(resource.id) if resource else None,
    )


@router.get("/datasets/{dataset_id}/preview")
async def preview(dataset_id: uuid.UUID, session: SessionDep, user: CurrentUserDep, limit: int = 100) -> dict:
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    try:
        await require_object_capability(session, user, "dataset", dataset_id, "view_data")
    except PermissionDenied:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing capability: view_data")

    result = await governed_dataset_preview(session, user, ds, limit=limit)
    rows = result["rows"]
    await log_event(
        session, user=user, event_type="DATASET_VIEWED",
        resource_type="dataset_preview", resource_id=str(dataset_id),
        output_summary={"row_count": len(rows)},
    )
    await session.commit()
    return {"rows": rows, "row_count": len(rows)}


class ExploreStep(BaseModel):
    type: str  # "filter" or "aggregate"
    # For filter:
    column: str | None = None
    op: str | None = None
    value: Any = None
    # For aggregate:
    group_by: list[str] | None = []
    metrics: list[dict] | None = []


class ExplorePayload(BaseModel):
    steps: list[ExploreStep]


ALLOWED_EXPLORE_AGGREGATIONS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


@router.post("/datasets/{dataset_id}/explore")
async def explore_dataset(
    dataset_id: uuid.UUID,
    payload: ExplorePayload,
    session: SessionDep,
    user: CurrentUserDep
) -> dict:
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    try:
        await require_object_capability(session, user, "dataset", dataset_id, "view_data")
    except PermissionDenied:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing capability: view_data")

    from app.util.identifiers import assert_safe_ident
    assert_safe_ident(ds.schema_name)
    assert_safe_ident(ds.table_name)

    col_rows = await session.execute(
        select(DatasetColumn.name, DatasetColumn.data_type).where(DatasetColumn.dataset_id == dataset_id)
    )
    column_types = {name.lower(): (dtype or "").lower() for name, dtype in col_rows.all()}

    def _coerce_filter_value(column: str, value: object) -> object:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if not isinstance(value, str):
            return value
        dtype = column_types.get(column.lower(), "")
        stripped = value.strip()
        if any(token in dtype for token in ("int", "float", "double", "decimal", "numeric", "real", "bigint", "smallint")):
            if stripped and stripped.replace(".", "", 1).isdigit():
                return float(stripped) if "." in stripped else int(stripped)
        if "bool" in dtype and stripped.lower() in {"true", "false"}:
            return stripped.lower() == "true"
        return value

    base_sql = f'SELECT * FROM "{ds.schema_name}"."{ds.table_name}"'
    current_sql = base_sql
    sql_params = {}

    for idx, step in enumerate(payload.steps):
        if step.type == "filter":
            if not step.column or not step.op:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "filter steps require column and op")
            assert_safe_ident(step.column)
            valid_ops = {"==", "!=", "<", ">", "<=", ">=", "LIKE", "ILIKE", "="}
            op_str = step.op
            if op_str == "==":
                op_str = "="
            if op_str not in valid_ops:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid operator: {step.op}")
            
            param_name = f"param_{idx}"
            current_sql = f'SELECT * FROM ({current_sql}) AS _step_{idx} WHERE "{step.column}" {op_str} :{param_name}'
            sql_params[param_name] = _coerce_filter_value(step.column, step.value)

        elif step.type == "aggregate":
            group_by_cols = step.group_by or []
            for col in group_by_cols:
                assert_safe_ident(col)
            
            select_parts = [f'"{col}"' for col in group_by_cols]
            
            for m in (step.metrics or []):
                agg = (m.get("aggregation") or "count").upper()
                if agg not in ALLOWED_EXPLORE_AGGREGATIONS:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid aggregation: {agg}")
                col = m.get("column") or "*"
                if col == "*" and agg != "COUNT":
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{agg} requires a column")
                if col != "*":
                    assert_safe_ident(col)
                alias = m.get("alias") or f"{agg.lower()}_{col if col != '*' else 'all'}"
                assert_safe_ident(alias)
                col_sql = "*" if col == "*" else f'"{col}"'
                select_parts.append(f"{agg}({col_sql}) AS \"{alias}\"")

            if not select_parts:
                select_parts = ["*"]

            group_clause = ""
            if group_by_cols:
                group_clause = " GROUP BY " + ", ".join(f'"{c}"' for c in group_by_cols)

            current_sql = f'SELECT {", ".join(select_parts)} FROM ({current_sql}) AS _step_{idx}{group_clause}'
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown step type: {step.type}")

    try:
        result = await governed_query(
            session,
            user,
            current_sql,
            params=sql_params,
            dataset_ids=[dataset_id],
            capability="view_data",
            audit_resource_type="dataset_explore",
            audit_resource_id=str(dataset_id),
            use_cache=True,
        )
        rows = result["rows"]
        columns = result["columns"]
    except PermissionDenied:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing capability: view_data")
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Database execution failed: {e}")

    await log_event(
        session, user=user, event_type="DATASET_VIEWED",
        resource_type="dataset_explore", resource_id=str(dataset_id),
        output_summary={"row_count": len(rows)},
    )
    await session.commit()

    return {"columns": columns, "rows": rows}


@router.get("/datasets/{dataset_id}/versions", response_model=list[DatasetVersionOut])
async def list_dataset_versions(dataset_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[DatasetVersionOut]:
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    caps = await effective_capabilities_for_object(session, user, "dataset", dataset_id)
    if not ({"view_metadata", "manage"} & caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no metadata access")
    rows = (await session.execute(
        select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id).order_by(DatasetVersion.version_number.desc())
    )).scalars().all()
    return [
        DatasetVersionOut(
            id=str(v.id),
            version_number=v.version_number,
            schema_version_id=str(v.schema_version_id) if v.schema_version_id else None,
            storage_uri=v.storage_uri,
            manifest=v.manifest or {},
            row_count=v.row_count,
            file_count=v.file_count,
            content_hash=v.content_hash,
            branch_name=v.branch_name,
            quality_status=v.quality_status,
            state=v.state,
            created_at=v.created_at,
        )
        for v in rows
    ]


@router.get("/datasets/{dataset_id}/storage-manifests", response_model=list[DatasetStorageManifestOut])
async def list_dataset_storage_manifests(dataset_id: uuid.UUID, session: SessionDep, user: CurrentUserDep, version_id: uuid.UUID | None = None) -> list[DatasetStorageManifestOut]:
    await _require_dataset_cap(session, user, dataset_id, "view_metadata")
    stmt = select(DatasetStorageManifest).where(DatasetStorageManifest.dataset_id == dataset_id)
    if version_id:
        stmt = stmt.where(DatasetStorageManifest.dataset_version_id == version_id)
    rows = (await session.execute(stmt.order_by(DatasetStorageManifest.created_at.desc()).limit(100))).scalars().all()
    return [
        DatasetStorageManifestOut(
            id=str(row.id),
            dataset_id=str(row.dataset_id),
            dataset_version_id=str(row.dataset_version_id) if row.dataset_version_id else None,
            storage_uri=row.storage_uri,
            manifest=row.manifest or {},
            file_count=row.file_count,
            total_bytes=row.total_bytes,
            content_hash=row.content_hash,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/datasets/{dataset_id}/classifications/confirm")
async def confirm_dataset_classification(
    dataset_id: uuid.UUID,
    payload: ClassificationConfirmIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    ds = await _require_dataset_cap(session, user, dataset_id, "manage")
    profile = await get_latest_profile(session, dataset_id)
    next_profile = dict(profile.profile) if profile else {"columns": {}}
    columns = dict(next_profile.get("columns") or {})
    current = dict(columns.get(payload.column_name) or {})
    current["classifications"] = payload.classifications
    current["sensitivity"] = payload.sensitivity or current.get("sensitivity") or "internal"
    current["suggested_markings"] = payload.suggested_markings
    current["steward_confirmed"] = True
    current["confirmed_by"] = str(user.id)
    current["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    columns[payload.column_name] = current
    next_profile["columns"] = columns
    next_profile["quality_status"] = next_profile.get("quality_status") or "profiled"
    session.add(DatasetProfile(dataset_id=ds.id, dataset_version_id=ds.current_version_id, profile=next_profile))
    await log_event(
        session,
        user=user,
        event_type="DATASET_CLASSIFICATION_CONFIRMED",
        resource_type="dataset",
        resource_id=str(dataset_id),
        input_summary=payload.model_dump(mode="json"),
    )
    await session.commit()
    return {"ok": True}


async def _schema_cols(session, version: DatasetVersion) -> dict[str, Any]:
    if not version.schema_version_id:
        return {}
    sv = await session.get(DatasetSchemaVersion, version.schema_version_id)
    return {c["name"]: c for c in ((sv.schema if sv else []) or [])}


@router.post("/datasets/{dataset_id}/versions/{version_id}/promote")
async def promote_dataset_version(
    dataset_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, user: CurrentUserDep, force: bool = False,
) -> dict:
    ds = await _require_dataset_cap(session, user, dataset_id, "manage")
    version = await session.get(DatasetVersion, version_id)
    if version is None or version.dataset_id != dataset_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset version not found")

    # Quality gate: a version whose last quality run failed cannot be promoted
    # unless explicitly forced.
    if version.quality_status == "failed" and not force:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "version failed quality checks; pass force=true to promote anyway",
        )

    # Schema-drift gate: block breaking drift (removed or changed columns) vs the
    # current version unless forced. Added columns are non-breaking.
    breaking: list[str] = []
    if ds.current_version_id and ds.current_version_id != version.id:
        current = await session.get(DatasetVersion, ds.current_version_id)
        if current is not None:
            before = await _schema_cols(session, current)
            after = await _schema_cols(session, version)
            breaking = sorted(
                [k for k in before.keys() - after.keys()]
                + [k for k in before.keys() & after.keys() if before[k] != after[k]]
            )
    if breaking and not force:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"breaking schema drift on columns {breaking}; pass force=true to promote anyway",
        )

    ds.current_version_id = version.id
    ds.storage_uri = version.storage_uri or ds.storage_uri
    ds.row_count = version.row_count
    ds.transaction_id = str(version.id)
    await log_event(
        session, user=user, event_type="DATASET_VERSION_PROMOTED",
        resource_type="dataset", resource_id=str(dataset_id),
        output_summary={"version_id": str(version_id), "forced": force, "breaking_drift": breaking},
    )
    await session.commit()
    return {"ok": True, "dataset_id": str(dataset_id), "current_version_id": str(version_id), "breaking_drift": breaking}


@router.get("/datasets/{dataset_id}/versions/diff", response_model=SchemaDiffOut)
async def diff_dataset_versions(
    dataset_id: uuid.UUID,
    from_version_id: uuid.UUID,
    to_version_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
) -> SchemaDiffOut:
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found")
    caps = await effective_capabilities_for_object(session, user, "dataset", dataset_id)
    if not ({"view_metadata", "manage"} & caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no metadata access")
    from_v = await session.get(DatasetVersion, from_version_id)
    to_v = await session.get(DatasetVersion, to_version_id)
    if not from_v or not to_v or from_v.dataset_id != dataset_id or to_v.dataset_id != dataset_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset version not found")
    from_schema = await session.get(DatasetSchemaVersion, from_v.schema_version_id) if from_v.schema_version_id else None
    to_schema = await session.get(DatasetSchemaVersion, to_v.schema_version_id) if to_v.schema_version_id else None
    before = {c["name"]: c for c in ((from_schema.schema if from_schema else []) or [])}
    after = {c["name"]: c for c in ((to_schema.schema if to_schema else []) or [])}
    added = [after[k] for k in sorted(after.keys() - before.keys())]
    removed = [before[k] for k in sorted(before.keys() - after.keys())]
    changed = [
        {"name": k, "from": before[k], "to": after[k]}
        for k in sorted(before.keys() & after.keys())
        if before[k] != after[k]
    ]
    return SchemaDiffOut(from_version_id=str(from_version_id), to_version_id=str(to_version_id), added=added, removed=removed, changed=changed)


def _to_out(d: Dataset) -> DatasetOut:
    pipeline_id = None
    if d.schema_name == "mf_pipelines" and d.table_name.startswith("mf_pipeline_"):
        raw = d.table_name.removeprefix("mf_pipeline_").replace("_", "-")
        try:
            pipeline_id = str(uuid.UUID(raw))
        except ValueError:
            pipeline_id = None
    return DatasetOut(
        id=str(d.id),
        name=d.name,
        description=d.description,
        source_id=str(d.source_id) if d.source_id else None,
        schema_name=d.schema_name,
        table_name=d.table_name,
        row_count=d.row_count,
        ai_policy=d.ai_policy,
        derived_from_pipeline_id=pipeline_id,
        security_markings=d.security_markings or [],
        stewards=d.stewards or [],
        tags=d.tags or [],
        glossary_terms=d.glossary_terms or [],
        created_at=d.created_at,
        current_version_id=str(d.current_version_id) if d.current_version_id else None,
    )


# ---------------------------------------------------------------------------
# Branch endpoints
# ---------------------------------------------------------------------------

class BranchCreateIn(BaseModel):
    branch_name: str
    from_branch: str = "main"


class BranchOut(BaseModel):
    id: str
    dataset_id: str
    branch_name: str
    parent_branch: str
    status: str
    merged_into: str | None
    created_at: datetime


class MergeIn(BaseModel):
    target_branch: str = "main"


def _branch_out(t: BranchTransaction) -> BranchOut:
    return BranchOut(
        id=str(t.id),
        dataset_id=str(t.dataset_id),
        branch_name=t.branch_name,
        parent_branch=t.parent_branch,
        status=t.status,
        merged_into=t.merged_into,
        created_at=t.created_at,
    )


@router.get("/datasets/{dataset_id}/branches", response_model=list[BranchOut])
async def list_branches(dataset_id: uuid.UUID, session: SessionDep, user: CurrentUserDep):
    from app.data.branch_service import list_branches as svc_list
    await _require_dataset_cap(session, user, dataset_id, "view_metadata")
    branches = await svc_list(session, dataset_id)
    return [_branch_out(b) for b in branches]


@router.post("/datasets/{dataset_id}/branches", response_model=BranchOut, status_code=201)
async def create_branch(dataset_id: uuid.UUID, body: BranchCreateIn, session: SessionDep, user: CurrentUserDep):
    from app.data.branch_service import create_branch as svc_create
    await _require_dataset_cap(session, user, dataset_id, "edit")
    try:
        txn = await svc_create(session, dataset_id, body.branch_name, body.from_branch, user.id)
        await session.commit()
        return _branch_out(txn)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


async def _require_branch_transaction(session: SessionDep, dataset_id: uuid.UUID, transaction_id: uuid.UUID) -> BranchTransaction:
    txn = await session.get(BranchTransaction, transaction_id)
    if txn is None or txn.dataset_id != dataset_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "branch transaction not found")
    return txn


@router.post("/datasets/{dataset_id}/branches/{transaction_id}/commit", response_model=BranchOut)
async def commit_branch(dataset_id: uuid.UUID, transaction_id: uuid.UUID, session: SessionDep, user: CurrentUserDep):
    from app.data.branch_service import commit_branch as svc_commit
    await _require_dataset_cap(session, user, dataset_id, "edit")
    await _require_branch_transaction(session, dataset_id, transaction_id)
    try:
        txn = await svc_commit(session, transaction_id)
        await session.commit()
        return _branch_out(txn)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.post("/datasets/{dataset_id}/branches/{transaction_id}/merge")
async def merge_branch(dataset_id: uuid.UUID, transaction_id: uuid.UUID, body: MergeIn, session: SessionDep, user: CurrentUserDep):
    from app.data.branch_service import merge_branch as svc_merge
    await _require_dataset_cap(session, user, dataset_id, "edit")
    await _require_branch_transaction(session, dataset_id, transaction_id)
    try:
        report = await svc_merge(session, transaction_id, body.target_branch)
        await session.commit()
        return report
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/datasets/{dataset_id}/branches/{transaction_id}/diff")
async def diff_branch(dataset_id: uuid.UUID, transaction_id: uuid.UUID, session: SessionDep, user: CurrentUserDep):
    from app.data.branch_service import diff_branch as svc_diff
    await _require_dataset_cap(session, user, dataset_id, "view_data")
    await _require_branch_transaction(session, dataset_id, transaction_id)
    try:
        return await svc_diff(session, transaction_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.delete("/datasets/{dataset_id}/branches/{transaction_id}", response_model=BranchOut)
async def abort_branch(dataset_id: uuid.UUID, transaction_id: uuid.UUID, session: SessionDep, user: CurrentUserDep):
    from app.data.branch_service import abort_branch as svc_abort
    await _require_dataset_cap(session, user, dataset_id, "edit")
    await _require_branch_transaction(session, dataset_id, transaction_id)
    try:
        txn = await svc_abort(session, transaction_id)
        await session.commit()
        return _branch_out(txn)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/lineage", response_model=LineageOut)
async def get_lineage(session: SessionDep, user: CurrentUserDep) -> LineageOut:
    datasets = await list_visible_datasets(session, user.id)

    from app.pipelines.models import Pipeline, PipelineNode
    from sqlalchemy import select

    pq = await session.execute(select(Pipeline))
    pipelines = list(pq.scalars().all())

    nodes = []
    edges = []

    dataset_ids = {d.id for d in datasets}

    for d in datasets:
        nodes.append(LineageNode(
            id=str(d.id),
            type="dataset",
            name=d.name,
            row_count=d.row_count,
            description=d.description
        ))

    for p in pipelines:
        if not p.output_dataset_id:
            continue
        if p.output_dataset_id not in dataset_ids:
            continue

        nodes.append(LineageNode(
            id=str(p.id),
            type="pipeline",
            name=p.name,
            description=p.description
        ))

        edges.append(LineageEdge(
            id=f"e-{p.id}-{p.output_dataset_id}",
            source=str(p.id),
            target=str(p.output_dataset_id)
        ))

        nq = await session.execute(
            select(PipelineNode)
            .where(PipelineNode.pipeline_id == p.id)
            .where(PipelineNode.node_type == "source")
        )
        sources = nq.scalars().all()
        for src in sources:
            src_ds_id = (src.config or {}).get("dataset_id")
            if src_ds_id:
                try:
                    src_uuid = uuid.UUID(str(src_ds_id))
                    if src_uuid in dataset_ids:
                        edges.append(LineageEdge(
                            id=f"e-{src_uuid}-{p.id}",
                            source=str(src_uuid),
                            target=str(p.id)
                        ))
                except ValueError:
                    pass

    return LineageOut(nodes=nodes, edges=edges)


# =========================================================================
# Quality rules, versioned results, and freshness
# =========================================================================


class QualityRuleIn(BaseModel):
    column_name: str | None = None
    rule_type: str
    rule_value: str | None = None
    severity: str = "error"
    branch_name: str = "main"


class QualityRuleOut(BaseModel):
    id: str
    column_name: str | None
    rule_type: str
    rule_value: str | None
    severity: str


class QualityResultOut(BaseModel):
    id: str
    run_id: str
    dataset_version_id: str | None
    expectation_id: str | None
    rule_type: str
    column_name: str | None
    severity: str
    passed: bool
    failed_records: int
    message: str | None
    checked_at: datetime


class QualityRunOut(BaseModel):
    run_id: str
    status: str
    results: list[QualityResultOut]


@router.get("/datasets/{dataset_id}/quality-rules", response_model=list[QualityRuleOut])
async def list_quality_rules(dataset_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[QualityRuleOut]:
    await _require_dataset_cap(session, user, dataset_id, "view_metadata")
    rows = (await session.execute(select(Expectation).where(Expectation.dataset_id == dataset_id))).scalars().all()
    return [
        QualityRuleOut(id=str(e.id), column_name=e.column_name, rule_type=e.rule_type, rule_value=e.rule_value, severity=e.severity)
        for e in rows
    ]


@router.post("/datasets/{dataset_id}/quality-rules", response_model=QualityRuleOut)
async def create_quality_rule(dataset_id: uuid.UUID, payload: QualityRuleIn, session: SessionDep, user: CurrentUserDep) -> QualityRuleOut:
    ds = await _require_dataset_cap(session, user, dataset_id, "edit")
    if payload.rule_type not in QUALITY_RULE_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"rule_type must be one of {sorted(QUALITY_RULE_TYPES)}")
    if payload.severity not in QUALITY_SEVERITIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"severity must be one of {sorted(QUALITY_SEVERITIES)}")
    if payload.rule_type != "unique" and not payload.column_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "column_name is required for this rule type")
    e = Expectation(
        dataset_id=dataset_id, column_name=payload.column_name, rule_type=payload.rule_type,
        rule_value=payload.rule_value, severity=payload.severity,
    )
    session.add(e)
    await session.flush()
    await _register_dataset_contract_version(
        session,
        ds,
        user.id,
        payload.branch_name,
        "quality_rule_created",
        {"rule_id": str(e.id), "rule_type": e.rule_type, "column_name": e.column_name, "severity": e.severity},
    )
    await log_event(session, user=user, event_type="DATASET_QUALITY_RULE_EDITED", resource_type="dataset", resource_id=str(dataset_id), input_summary={"action": "create", "rule_type": e.rule_type})
    await session.commit()
    return QualityRuleOut(id=str(e.id), column_name=e.column_name, rule_type=e.rule_type, rule_value=e.rule_value, severity=e.severity)


@router.delete("/datasets/{dataset_id}/quality-rules/{rule_id}")
async def delete_quality_rule(dataset_id: uuid.UUID, rule_id: uuid.UUID, session: SessionDep, user: CurrentUserDep, branch_name: str = "main") -> dict:
    ds = await _require_dataset_cap(session, user, dataset_id, "edit")
    e = await session.get(Expectation, rule_id)
    if e is None or e.dataset_id != dataset_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "rule not found")
    await _register_dataset_contract_version(
        session,
        ds,
        user.id,
        branch_name,
        "quality_rule_deleted",
        {"rule_id": str(e.id), "rule_type": e.rule_type, "column_name": e.column_name, "severity": e.severity},
    )
    await session.delete(e)
    await log_event(session, user=user, event_type="DATASET_QUALITY_RULE_EDITED", resource_type="dataset", resource_id=str(dataset_id), input_summary={"action": "delete"})
    await session.commit()
    return {"ok": True}


@router.post("/datasets/{dataset_id}/quality-run", response_model=QualityRunOut)
async def run_quality_checks(dataset_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> QualityRunOut:
    ds = await _require_dataset_cap(session, user, dataset_id, "edit")
    try:
        results = await validate_expectations_async(session, dataset_id)
    except ExpectationFailedError as e:
        results = e.failures  # error-severity failures still carry the per-rule results

    run_id = uuid.uuid4()
    version_id = ds.current_version_id
    for r in results:
        session.add(QualityResult(
            dataset_id=dataset_id, dataset_version_id=version_id, run_id=run_id,
            expectation_id=uuid.UUID(r["expectation_id"]) if r.get("expectation_id") else None,
            rule_type=r["rule_type"], column_name=r.get("column_name"), severity=r.get("severity", "error"),
            passed=bool(r["passed"]), failed_records=int(r.get("failed_records_count") or 0),
            message=r.get("error_message"),
        ))

    has_error_fail = any(not r["passed"] and r.get("severity") == "error" for r in results)
    has_warn_fail = any(not r["passed"] and r.get("severity") != "error" for r in results)
    overall = "unknown" if not results else ("failed" if has_error_fail else ("warning" if has_warn_fail else "passed"))

    if version_id:
        v = await session.get(DatasetVersion, version_id)
        if v is not None:
            v.quality_status = overall

    await log_event(session, user=user, event_type="DATASET_QUALITY_RUN", resource_type="dataset", resource_id=str(dataset_id), output_summary={"run_id": str(run_id), "status": overall})
    await session.commit()

    out_rows = (await session.execute(
        select(QualityResult).where(QualityResult.run_id == run_id).order_by(QualityResult.checked_at)
    )).scalars().all()
    return QualityRunOut(run_id=str(run_id), status=overall, results=[_quality_result_out(r) for r in out_rows])


def _quality_result_out(r: QualityResult) -> QualityResultOut:
    return QualityResultOut(
        id=str(r.id), run_id=str(r.run_id),
        dataset_version_id=str(r.dataset_version_id) if r.dataset_version_id else None,
        expectation_id=str(r.expectation_id) if r.expectation_id else None,
        rule_type=r.rule_type, column_name=r.column_name, severity=r.severity,
        passed=r.passed, failed_records=r.failed_records, message=r.message, checked_at=r.checked_at,
    )


@router.get("/datasets/{dataset_id}/quality-results", response_model=list[QualityResultOut])
async def get_quality_results(dataset_id: uuid.UUID, session: SessionDep, user: CurrentUserDep, version_id: uuid.UUID | None = None) -> list[QualityResultOut]:
    await _require_dataset_cap(session, user, dataset_id, "view_metadata")
    stmt = select(QualityResult).where(QualityResult.dataset_id == dataset_id)
    if version_id:
        stmt = stmt.where(QualityResult.dataset_version_id == version_id)
    # Latest run only: find the most recent run_id, then its rows.
    latest = (await session.execute(stmt.order_by(QualityResult.checked_at.desc()).limit(1))).scalar_one_or_none()
    if latest is None:
        return []
    rows = (await session.execute(
        select(QualityResult).where(QualityResult.run_id == latest.run_id).order_by(QualityResult.checked_at)
    )).scalars().all()
    return [_quality_result_out(r) for r in rows]


class FreshnessOut(BaseModel):
    last_updated: datetime | None
    age_seconds: int | None
    window_seconds: int | None
    status: str  # fresh | stale | unknown


class FreshnessIn(BaseModel):
    window_seconds: int | None
    branch_name: str = "main"


async def _register_dataset_contract_version(session: SessionDep, ds: Dataset, user_id: uuid.UUID, branch_name: str, kind: str, details: dict) -> None:
    resource = await get_resource_for_object(session, "dataset", ds.id)
    if resource is None:
        return
    await register_resource_version(
        session,
        resource=resource,
        created_by=user_id,
        branch_name=branch_name or "main",
        manifest={"kind": kind, "branch_name": branch_name or "main", "dataset_contract": details},
    )


@router.get("/datasets/{dataset_id}/freshness", response_model=FreshnessOut)
async def get_freshness(dataset_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> FreshnessOut:
    ds = await _require_dataset_cap(session, user, dataset_id, "view_metadata")
    last_version = (await session.execute(
        select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id).order_by(DatasetVersion.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    last_updated = last_version.created_at if last_version else None
    if last_updated is None:
        profile = (await session.execute(
            select(DatasetProfile).where(DatasetProfile.dataset_id == dataset_id).order_by(DatasetProfile.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        last_updated = profile.created_at if profile else None

    window = ds.freshness_window_seconds
    age = None
    fstatus = "unknown"
    if last_updated is not None:
        now = datetime.now(timezone.utc)
        ref = last_updated if last_updated.tzinfo else last_updated.replace(tzinfo=timezone.utc)
        age = int((now - ref).total_seconds())
        if window is not None:
            fstatus = "fresh" if age <= window else "stale"
    return FreshnessOut(last_updated=last_updated, age_seconds=age, window_seconds=window, status=fstatus)


@router.put("/datasets/{dataset_id}/freshness", response_model=FreshnessOut)
async def set_freshness(dataset_id: uuid.UUID, payload: FreshnessIn, session: SessionDep, user: CurrentUserDep) -> FreshnessOut:
    ds = await _require_dataset_cap(session, user, dataset_id, "edit")
    if payload.window_seconds is not None and payload.window_seconds < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "window_seconds must be >= 0")
    ds.freshness_window_seconds = payload.window_seconds
    await _register_dataset_contract_version(
        session,
        ds,
        user.id,
        payload.branch_name,
        "freshness_contract_updated",
        {"freshness_window_seconds": payload.window_seconds},
    )
    await session.commit()
    return await get_freshness(dataset_id, session, user)
