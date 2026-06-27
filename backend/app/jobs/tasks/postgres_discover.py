"""Background Postgres schema discovery task.

The web endpoint creates the DataSource row, enqueues this task with the
connection config + ai_policy, then returns immediately. The task does the
slow schema discovery and inserts Dataset + DatasetColumn rows.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.connectors.postgres import PostgresConnector
from app.data.models import Dataset, DatasetColumn
from app.jobs.registry import job_task
from app.jobs.service_sync import report_progress
from app.permissions.models import PermissionVersion
from app.platform.service import upsert_resource_sync


@job_task("postgres_discover")
def run(session, job, input: dict[str, Any]) -> dict[str, Any]:
    source_id = uuid.UUID(input["source_id"])
    owner_id = uuid.UUID(input["owner_id"])
    ai_policy = input.get("ai_policy", "local_only")
    name = input.get("name", "postgres")

    from app.data.models import DataSource
    from app.permissions.secrets import get_secret_sync
    source = session.get(DataSource, source_id)
    if source is None:
        raise ValueError(f"DataSource {source_id} not found")

    config = dict(source.connection_config)
    existing_datasets = (
        session.query(Dataset)
        .filter(Dataset.source_id == source_id)
        .order_by(Dataset.created_at.asc())
        .all()
    )
    if config.get("managed") and existing_datasets:
        source.status = "ok"
        return {
            "datasets": [{"id": str(ds.id), "name": ds.name} for ds in existing_datasets],
            "count": len(existing_datasets),
            "managed": True,
        }

    if source.secret_ref:
        password = get_secret_sync(session, uuid.UUID(source.secret_ref))
        config["password"] = password

    conn = PostgresConnector(config)
    conn.test_connection()
    tables = conn.discover_schema()

    created: list[dict[str, str]] = []
    existing_by_table = {
        (ds.schema_name, ds.table_name): ds
        for ds in existing_datasets
    }
    total = max(1, len(tables))
    for i, t in enumerate(tables):
        report_progress(session, job, percent=(i / total) * 100, message=f"Discovering {t['schema']}.{t['table']}")
        existing = existing_by_table.get((t["schema"], t["table"]))
        if existing is not None:
            created.append({"id": str(existing.id), "name": existing.name})
            continue
        ds = Dataset(
            source_id=source_id,
            name=f"{name}.{t['schema']}.{t['table']}",
            schema_name=t["schema"],
            table_name=t["table"],
            ai_policy=ai_policy,
            owner_id=owner_id,
        )
        session.add(ds)
        session.flush()
        for c in t["columns"]:
            session.add(DatasetColumn(dataset_id=ds.id, name=c["name"], data_type=c["type"]))
        upsert_resource_sync(
            session,
            resource_type="dataset",
            object_id=ds.id,
            name=ds.name,
            owner_user_id=owner_id,
            metadata={"schema_name": ds.schema_name, "table_name": ds.table_name},
        )
        created.append({"id": str(ds.id), "name": ds.name})

    source.status = "ok"
    # Bump shared permission version
    pv = session.get(PermissionVersion, "global")
    if pv is None:
        session.add(PermissionVersion(scope="global", version=2))
    else:
        pv.version = int(pv.version) + 1
    session.flush()

    return {"datasets": created, "count": len(created)}
