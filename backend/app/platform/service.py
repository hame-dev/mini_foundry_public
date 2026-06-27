from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.data.models import Dataset, DatasetColumn, DatasetStorageManifest
from app.platform.models import (
    BuildInput,
    BuildLog,
    BuildOutput,
    BuildRun,
    DatasetSchemaVersion,
    DatasetVersion,
    LineageEdge,
    Marking,
    Project,
    Resource,
    ResourceACL,
    ResourceMarking,
    ResourceVersion,
)


RESOURCE_TYPES = {
    "project",
    "folder",
    "dataset",
    "pipeline",
    "dashboard",
    "notebook",
    "ontology_object_type",
    "ontology_relationship",
    "ontology_action",
    "ontology_object_set",
    "code_repository",
    "saved_query",
    "model",
    "application",
    "workflow",
    "schedule",
    "data_source",
    "media_set",
}

CANONICAL_CAPABILITIES = {
    "view_metadata",
    "view_data",
    "use_in_sql",
    "use_in_python",
    "use_with_ai",
    "run",
    "edit",
    "manage",
    "export",
    "grant",
    "publish",
    "writeback",
}

OWNER_CAPABILITIES = sorted(CANONICAL_CAPABILITIES)


async def ensure_default_project(session: AsyncSession, owner: User | None = None) -> Project:
    result = await session.execute(select(Project).where(Project.name == "Default Project", Project.deleted_at.is_(None)))
    project = result.scalar_one_or_none()
    if project:
        return project
    project = Project(name="Default Project", description="Default project for migrated Mini Foundry resources", owner_id=owner.id if owner else None)
    session.add(project)
    await session.flush()
    return project


async def upsert_resource(
    session: AsyncSession,
    *,
    resource_type: str,
    object_id: uuid.UUID | None,
    name: str,
    owner_user_id: uuid.UUID | None,
    project_id: uuid.UUID | None = None,
    parent_resource_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> Resource:
    if resource_type not in RESOURCE_TYPES:
        raise ValueError(f"unknown resource_type: {resource_type}")
    resource = None
    if object_id is not None:
        resource = (
            await session.execute(
                select(Resource).where(Resource.resource_type == resource_type, Resource.object_id == object_id)
            )
        ).scalar_one_or_none()
    created = resource is None
    changed = True
    if resource is None:
        if project_id is None:
            project = await ensure_default_project(session)
            project_id = project.id
        resource = Resource(
            resource_type=resource_type,
            object_id=object_id,
            name=name,
            owner_user_id=owner_user_id,
            project_id=project_id,
            parent_resource_id=parent_resource_id,
            resource_metadata=metadata or {},
        )
        session.add(resource)
        await session.flush()
    else:
        before = {
            "name": resource.name,
            "owner_user_id": str(resource.owner_user_id) if resource.owner_user_id else None,
            "project_id": str(resource.project_id) if resource.project_id else None,
            "parent_resource_id": str(resource.parent_resource_id) if resource.parent_resource_id else None,
            "metadata": resource.resource_metadata or {},
        }
        resource.name = name
        resource.owner_user_id = owner_user_id
        resource.project_id = project_id or resource.project_id
        resource.parent_resource_id = parent_resource_id if parent_resource_id is not None else resource.parent_resource_id
        resource.resource_metadata = {**(resource.resource_metadata or {}), **(metadata or {})}
        resource.updated_at = datetime.utcnow()
        changed = before != {
            "name": resource.name,
            "owner_user_id": str(resource.owner_user_id) if resource.owner_user_id else None,
            "project_id": str(resource.project_id) if resource.project_id else None,
            "parent_resource_id": str(resource.parent_resource_id) if resource.parent_resource_id else None,
            "metadata": resource.resource_metadata or {},
        }
    await grant_owner_acl(session, resource, owner_user_id)
    if created or changed:
        await register_resource_version(session, resource=resource, created_by=owner_user_id)
    return resource


async def register_resource_version(
    session: AsyncSession,
    *,
    resource: Resource,
    created_by: uuid.UUID | None = None,
    branch_name: str = "main",
    manifest: dict[str, Any] | None = None,
) -> ResourceVersion:
    version_number = await next_number(session, ResourceVersion, "version_number", "resource_id", resource.id)
    payload = {
        "resource_type": resource.resource_type,
        "object_id": str(resource.object_id) if resource.object_id else None,
        "name": resource.name,
        "project_id": str(resource.project_id) if resource.project_id else None,
        "parent_resource_id": str(resource.parent_resource_id) if resource.parent_resource_id else None,
        "owner_user_id": str(resource.owner_user_id) if resource.owner_user_id else None,
        "metadata": resource.resource_metadata or {},
        **(manifest or {}),
    }
    row = ResourceVersion(
        resource_id=resource.id,
        version_number=version_number,
        branch_name=branch_name,
        manifest=payload,
        created_by=created_by,
    )
    session.add(row)
    await session.flush()
    return row


async def grant_owner_acl(session: AsyncSession, resource: Resource, owner_user_id: uuid.UUID | None) -> None:
    if owner_user_id is None:
        return
    acl = (
        await session.execute(
            select(ResourceACL).where(
                ResourceACL.resource_id == resource.id,
                ResourceACL.subject_type == "user",
                ResourceACL.subject_id == owner_user_id,
            )
        )
    ).scalar_one_or_none()
    if acl is None:
        session.add(ResourceACL(resource_id=resource.id, subject_type="user", subject_id=owner_user_id, capabilities=OWNER_CAPABILITIES))
    else:
        acl.capabilities = sorted(set(acl.capabilities or []) | set(OWNER_CAPABILITIES))


def grant_owner_acl_sync(session, resource: Resource, owner_user_id: uuid.UUID | None) -> None:
    """Sync mirror of :func:`grant_owner_acl` for worker/job contexts."""
    if owner_user_id is None:
        return
    acl = (
        session.query(ResourceACL)
        .filter(
            ResourceACL.resource_id == resource.id,
            ResourceACL.subject_type == "user",
            ResourceACL.subject_id == owner_user_id,
        )
        .first()
    )
    if acl is None:
        session.add(ResourceACL(resource_id=resource.id, subject_type="user", subject_id=owner_user_id, capabilities=OWNER_CAPABILITIES))
    else:
        acl.capabilities = sorted(set(acl.capabilities or []) | set(OWNER_CAPABILITIES))


def upsert_resource_sync(
    session,
    *,
    resource_type: str,
    object_id: uuid.UUID,
    name: str,
    owner_user_id: uuid.UUID | None,
    project_id: uuid.UUID | None = None,
    parent_resource_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> Resource:
    """Sync mirror of :func:`upsert_resource`.

    Find-or-create the ``Resource`` row for ``(resource_type, object_id)`` and
    grant the owner a full-capability ACL. Used by worker/job code paths that
    run on a synchronous ``Session`` (e.g. notebook scratch datasets, postgres
    discovery) so every platform object has a resource at creation time.
    """
    if resource_type not in RESOURCE_TYPES:
        raise ValueError(f"unknown resource_type: {resource_type}")
    resource = (
        session.query(Resource)
        .filter(Resource.resource_type == resource_type, Resource.object_id == object_id)
        .first()
    )
    if resource is None:
        if project_id is None:
            project = (
                session.query(Project)
                .filter(Project.name == "Default Project", Project.deleted_at.is_(None))
                .first()
            )
            if project is None:
                project = Project(name="Default Project", description="Default project for migrated Mini Foundry resources", owner_id=owner_user_id)
                session.add(project)
                session.flush()
            project_id = project.id
        resource = Resource(
            resource_type=resource_type,
            object_id=object_id,
            name=name,
            owner_user_id=owner_user_id,
            project_id=project_id,
            parent_resource_id=parent_resource_id,
            resource_metadata=metadata or {},
        )
        session.add(resource)
        session.flush()
    else:
        resource.name = name
        resource.owner_user_id = owner_user_id
        resource.project_id = project_id or resource.project_id
        if parent_resource_id is not None:
            resource.parent_resource_id = parent_resource_id
        resource.resource_metadata = {**(resource.resource_metadata or {}), **(metadata or {})}
        resource.updated_at = datetime.utcnow()
    grant_owner_acl_sync(session, resource, owner_user_id)
    return resource


async def sync_resource_markings(session: AsyncSession, resource: Resource, marking_names: list[str]) -> None:
    for name in marking_names or []:
        marking = (await session.execute(select(Marking).where(Marking.name == name))).scalar_one_or_none()
        if marking is None:
            marking = Marking(name=name)
            session.add(marking)
            await session.flush()
        existing = (
            await session.execute(
                select(ResourceMarking).where(ResourceMarking.resource_id == resource.id, ResourceMarking.marking_id == marking.id)
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(ResourceMarking(resource_id=resource.id, marking_id=marking.id))


async def get_resource_for_object(session: AsyncSession, resource_type: str, object_id: uuid.UUID) -> Resource | None:
    return (
        await session.execute(select(Resource).where(Resource.resource_type == resource_type, Resource.object_id == object_id))
    ).scalar_one_or_none()


async def next_number(session: AsyncSession, model: type, column_name: str, resource_column: str, resource_id: uuid.UUID) -> int:
    column = getattr(model, column_name)
    resource_col = getattr(model, resource_column)
    value = (await session.execute(select(func.max(column)).where(resource_col == resource_id))).scalar_one_or_none()
    return int(value or 0) + 1


async def register_dataset_version(
    session: AsyncSession,
    *,
    dataset: Dataset,
    columns: list[DatasetColumn] | None = None,
    storage_uri: str | None = None,
    manifest: dict[str, Any] | None = None,
    content_hash: str | None = None,
    state: str = "available",
    created_by: uuid.UUID | None = None,
    created_by_job_id: uuid.UUID | None = None,
    created_by_build_id: uuid.UUID | None = None,
) -> DatasetVersion:
    version_number = await next_number(session, DatasetVersion, "version_number", "dataset_id", dataset.id)
    if columns is None:
        columns = list(
            (await session.execute(select(DatasetColumn).where(DatasetColumn.dataset_id == dataset.id).order_by(DatasetColumn.name)))
            .scalars()
            .all()
        )
    schema_payload = [{"name": c.name, "type": c.data_type, "description": c.description} for c in columns]
    schema_version = DatasetSchemaVersion(dataset_id=dataset.id, version_number=version_number, schema=schema_payload)
    session.add(schema_version)
    await session.flush()
    merged_manifest = {
        "schema_name": dataset.schema_name,
        "table_name": dataset.table_name,
        "execution_engine": dataset.execution_engine,
        "storage_uri": storage_uri or dataset.storage_uri,
        **(manifest or {}),
    }
    if content_hash is None:
        content_hash = hashlib.sha256(repr(merged_manifest).encode()).hexdigest()
    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=version_number,
        schema_version_id=schema_version.id,
        storage_uri=storage_uri or dataset.storage_uri,
        manifest=merged_manifest,
        row_count=dataset.row_count,
        file_count=merged_manifest.get("file_count", 1 if (storage_uri or dataset.storage_uri) else None),
        content_hash=content_hash,
        branch_name=dataset.branch_name or "main",
        state=state,
        created_by=created_by,
        created_by_job_id=created_by_job_id,
        created_by_build_id=created_by_build_id,
    )
    session.add(version)
    await session.flush()
    session.add(DatasetStorageManifest(
        dataset_id=dataset.id,
        dataset_version_id=version.id,
        storage_uri=version.storage_uri,
        manifest=merged_manifest,
        file_count=version.file_count,
        total_bytes=merged_manifest.get("total_bytes"),
        content_hash=version.content_hash,
    ))
    dataset.transaction_id = str(version.id)
    return version


async def latest_dataset_version(session: AsyncSession, dataset_id: uuid.UUID) -> DatasetVersion | None:
    return (
        await session.execute(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id)
            .order_by(DatasetVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def resolve_dataset_version(
    session: AsyncSession, dataset_id: uuid.UUID, *, branch_name: str | None = None
) -> DatasetVersion | None:
    """Branch-aware version resolution — the single entry point for "which
    version is current".

    Returns the latest ``DatasetVersion`` on ``branch_name`` (defaulting to the
    dataset's own branch, or ``main``). Falls back to the overall latest version
    when the branch has no versions yet, so callers always get a sensible
    snapshot. Prefer this over :func:`latest_dataset_version`, which ignores the
    branch.
    """
    if branch_name is None:
        ds = await session.get(Dataset, dataset_id)
        branch_name = (getattr(ds, "branch_name", None) or "main") if ds else "main"
    branched = (
        await session.execute(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id, DatasetVersion.branch_name == branch_name)
            .order_by(DatasetVersion.version_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if branched is not None:
        return branched
    return await latest_dataset_version(session, dataset_id)


def effective_schema(ds: Dataset, *, branch_name: str | None = None) -> str:
    """Physical schema a dataset's table lives in for a given branch.

    Single source of truth for branch->schema mapping: Postgres branches live in
    a ``mf_branch_<name>`` schema; everything else uses the dataset schema.
    """
    engine = getattr(ds, "execution_engine", None) or "postgres"
    branch = branch_name or getattr(ds, "branch_name", None) or "main"
    if engine == "postgres" and branch != "main":
        return f"mf_branch_{branch.lower().replace('-', '_')}"
    return getattr(ds, "schema_name", None) or "public"


async def record_lineage(
    session: AsyncSession,
    *,
    source_resource_id: uuid.UUID | None,
    target_resource_id: uuid.UUID | None,
    edge_type: str,
    source_version_id: uuid.UUID | None = None,
    target_version_id: uuid.UUID | None = None,
    created_by_job_id: uuid.UUID | None = None,
    created_by_build_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> LineageEdge:
    edge = LineageEdge(
        source_resource_id=source_resource_id,
        source_version_id=source_version_id,
        target_resource_id=target_resource_id,
        target_version_id=target_version_id,
        edge_type=edge_type,
        created_by_job_id=created_by_job_id,
        created_by_build_id=created_by_build_id,
        edge_metadata=metadata or {},
    )
    session.add(edge)
    await session.flush()
    return edge


async def create_build_run(
    session: AsyncSession,
    *,
    pipeline_id: uuid.UUID | None,
    created_by: uuid.UUID | None,
    trigger_type: str = "manual",
    idempotency_key: str | None = None,
    compiled_plan: dict[str, Any] | None = None,
) -> BuildRun:
    run = BuildRun(
        pipeline_id=pipeline_id,
        created_by=created_by,
        trigger_type=trigger_type,
        idempotency_key=idempotency_key,
        status="running",
        started_at=datetime.utcnow(),
        compiled_plan=compiled_plan,
    )
    session.add(run)
    await session.flush()
    return run


async def finish_build_run(session: AsyncSession, build: BuildRun, *, status: str, error_summary: str | None = None) -> None:
    build.status = status
    build.error_summary = error_summary
    build.finished_at = datetime.utcnow()
    session.add(BuildLog(build_run_id=build.id, level="error" if status == "failed" else "info", message=status, payload={"error": error_summary} if error_summary else None))
    if status == "failed" and build.created_by:
        from app.notifications.service import create_notification

        await create_notification(
            session,
            user_id=build.created_by,
            topic="build_failure",
            title="Build failed",
            body=error_summary,
            resource_type="build_run",
            resource_id=str(build.id),
        )


async def add_build_input(session: AsyncSession, build_id: uuid.UUID, dataset: Dataset) -> BuildInput:
    version = await latest_dataset_version(session, dataset.id)
    row = BuildInput(build_run_id=build_id, dataset_id=dataset.id, dataset_version_id=version.id if version else None)
    session.add(row)
    return row


async def add_build_output(session: AsyncSession, build_id: uuid.UUID, dataset: Dataset, version: DatasetVersion | None) -> BuildOutput:
    row = BuildOutput(build_run_id=build_id, dataset_id=dataset.id, dataset_version_id=version.id if version else None)
    session.add(row)
    return row


async def sync_existing_resources(session: AsyncSession) -> None:
    """Best-effort backfill so existing feature rows appear in the resource graph."""
    project = await ensure_default_project(session)

    rows = (await session.execute(select(Dataset))).scalars().all()
    for ds in rows:
        resource = await upsert_resource(
            session,
            resource_type="dataset",
            object_id=ds.id,
            name=ds.name,
            owner_user_id=ds.owner_id,
            project_id=project.id,
            metadata={"schema_name": ds.schema_name, "table_name": ds.table_name, "storage_uri": ds.storage_uri},
        )
        await sync_resource_markings(session, resource, ds.security_markings or [])
        if ds.current_version_id is None:
            existing = await latest_dataset_version(session, ds.id)
            if existing is None:
                version = await register_dataset_version(session, dataset=ds, created_by=ds.owner_id)
                ds.current_version_id = version.id
            else:
                ds.current_version_id = existing.id

    from app.data.models import DataSource
    for source in (await session.execute(select(DataSource))).scalars().all():
        await upsert_resource(
            session,
            resource_type="data_source",
            object_id=source.id,
            name=source.name,
            owner_user_id=source.owner_id,
            project_id=project.id,
            metadata={"source_type": source.source_type},
        )

    from app.pipelines.models import Pipeline
    for pipeline in (await session.execute(select(Pipeline))).scalars().all():
        await upsert_resource(
            session,
            resource_type="pipeline",
            object_id=pipeline.id,
            name=pipeline.name,
            owner_user_id=pipeline.owner_id,
            project_id=project.id,
            metadata={"materialization_type": pipeline.materialization_type, "output_dataset_id": str(pipeline.output_dataset_id) if pipeline.output_dataset_id else None},
        )

    from app.dashboards.models import Dashboard, SavedQuery
    for dashboard in (await session.execute(select(Dashboard))).scalars().all():
        await upsert_resource(
            session,
            resource_type="dashboard",
            object_id=dashboard.id,
            name=dashboard.title,
            owner_user_id=dashboard.owner_id,
            project_id=project.id,
            metadata={"dashboard_kind": dashboard.dashboard_kind},
        )
    for query in (await session.execute(select(SavedQuery))).scalars().all():
        await upsert_resource(
            session,
            resource_type="saved_query",
            object_id=query.id,
            name=query.name,
            owner_user_id=query.owner_id,
            project_id=project.id,
            metadata={"dataset_ids": [str(x) for x in query.dataset_ids]},
        )

    from app.notebooks.models import Notebook
    for notebook in (await session.execute(select(Notebook))).scalars().all():
        await upsert_resource(
            session,
            resource_type="notebook",
            object_id=notebook.id,
            name=notebook.title,
            owner_user_id=notebook.owner_id,
            project_id=project.id,
            metadata={"kernel_name": getattr(notebook, "kernel_name", None)},
        )

    from app.code_repo.models import CodeRepository
    for repo in (await session.execute(select(CodeRepository))).scalars().all():
        await upsert_resource(
            session,
            resource_type="code_repository",
            object_id=repo.id,
            name=repo.name,
            owner_user_id=repo.owner_id,
            project_id=project.id,
            metadata={"repo_type": getattr(repo, "repo_type", None)},
        )

    from app.ml.models import MLModel
    for model in (await session.execute(select(MLModel))).scalars().all():
        await upsert_resource(
            session,
            resource_type="model",
            object_id=model.id,
            name=model.name,
            owner_user_id=model.owner_id,
            project_id=project.id,
            metadata={},
        )

    from app.ontology.models import OntologyAction, OntologyObject
    for obj in (await session.execute(select(OntologyObject))).scalars().all():
        resource = await upsert_resource(
            session,
            resource_type="ontology_object_type",
            object_id=obj.id,
            name=obj.type_name,
            owner_user_id=None,
            project_id=project.id,
            metadata={"dataset_id": str(obj.dataset_id), "primary_key": obj.primary_key},
        )
        dataset_resource = await get_resource_for_object(session, "dataset", obj.dataset_id)
        dataset_version = await latest_dataset_version(session, obj.dataset_id)
        if dataset_resource:
            await record_lineage(
                session,
                source_resource_id=dataset_resource.id,
                source_version_id=dataset_version.id if dataset_version else None,
                target_resource_id=resource.id,
                edge_type="dataset_to_ontology_object_type",
            )
    for action in (await session.execute(select(OntologyAction))).scalars().all():
        await upsert_resource(
            session,
            resource_type="ontology_action",
            object_id=action.id,
            name=action.name,
            owner_user_id=None,
            project_id=project.id,
            metadata={"object_type": action.object_type, "workflow_key": action.workflow_key},
        )

    from app.applications.models import Application
    for app in (await session.execute(select(Application))).scalars().all():
        await upsert_resource(
            session,
            resource_type="application",
            object_id=app.id,
            name=app.name,
            owner_user_id=app.owner_id,
            project_id=project.id,
            metadata={"status": app.status},
        )
