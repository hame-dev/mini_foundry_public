"""Worker-side notebook cell execution.

The Celery `notebook_cell` task hands off to `execute_cell_in_worker(session,
job, input)`. The web router has already validated permissions before
enqueueing, but we re-check inside the worker so revocations between enqueue
and run take effect.

Input shape:
  {
    "notebook_id": str(uuid),
    "cell_id": str(uuid),
    "source_snapshot": str,            # the cell source at enqueue time
    "cell_type": "python" | "ai_prompt",
    "dataset_ids": [str(uuid), ...],
    "user_id": str(uuid),
    # ai_prompt only:
    "run_after_generate": bool,
    "provider": str,
    "model": str | None,
  }
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.notebooks.models import Notebook, NotebookCell


# ---------------------------------------------------------------- helpers

def _read_dataset_to_parquet(
    session: Session,
    user_id: uuid.UUID | None,
    ds: "Dataset",
    target: Path,
) -> None:
    """Read a dataset into parquet, honoring branch schemas and storage backends."""
    from app.data.models import Dataset
    from app.execution.sql_runner import _get_external_postgres_engine, _is_managed_postgres_source
    from app.governed_query.service import _effective_schema

    schema = _effective_schema(ds)
    engine_name = getattr(ds, "execution_engine", None) or "postgres"
    source_id = getattr(ds, "source_id", None)

    if engine_name == "duckdb" and ds.storage_uri:
        df = pd.read_parquet(ds.storage_uri)
    elif source_id and not _is_managed_postgres_source(str(source_id)):
        ext_engine = _get_external_postgres_engine(str(source_id))
        df = pd.read_sql(text(f'SELECT * FROM "{schema}"."{ds.table_name}"'), ext_engine)
    else:
        sql = f'SELECT * FROM "{schema}"."{ds.table_name}"'
        if user_id:
            from app.permissions.row_policy import apply_row_policies_sync
            sql = apply_row_policies_sync(session, user_id, sql)
        engine = create_engine(get_settings().sync_database_url)
        df = pd.read_sql(text(sql), engine)

    if user_id:
        from app.permissions.masking import resolve_column_masks_sync, apply_masks_to_df
        masks = resolve_column_masks_sync(session, user_id, ds.id)
        df = apply_masks_to_df(df, masks)

    df.to_parquet(target, index=False)


def _resolve_permitted_datasets(
    session: Session, dataset_ids: list[uuid.UUID], user_id: uuid.UUID | None
) -> dict[str, str]:
    """Return {dataset_name: parquet_path} for every queued dataset_id."""
    from app.data.models import Dataset
    from app.permissions.enforcement import require_object_capability_sync

    permitted: dict[str, str] = {}
    if not dataset_ids:
        return permitted

    parquet_dir = Path(tempfile.mkdtemp(prefix="mfsbx-data-"))
    for did in dataset_ids:
        ds = session.get(Dataset, did)
        if ds is None:
            continue
        if user_id is not None:
            require_object_capability_sync(session, user_id, "dataset", did, "use_in_python")
        target = parquet_dir / f"{ds.id.hex}.parquet"
        _read_dataset_to_parquet(session, user_id, ds, target)
        permitted[ds.name] = str(target)
    return permitted


def build_ontology_snapshot(
    session: Session, dataset_ids: list[uuid.UUID] | None
) -> dict[str, Any]:
    """Build a read-only ontology snapshot for the given backing datasets.

    Shipped into the sandbox so `platform_sdk.objects.<TypeName>` can resolve
    objects from the mounted dataset parquet without any network access. Only
    object types whose backing dataset is granted to this run are included.
    """
    if not dataset_ids:
        return {"object_types": [], "relationships": []}

    from app.data.models import Dataset
    from app.ontology.models import OntologyObject, OntologyRelationship

    granted = set(dataset_ids)
    object_types: list[dict[str, Any]] = []
    type_names: set[str] = set()

    objs = session.execute(
        select(OntologyObject).where(OntologyObject.dataset_id.in_(granted))
    ).scalars().all()
    for obj in objs:
        ds = session.get(Dataset, obj.dataset_id)
        if ds is None:
            continue
        object_types.append({
            "type_name": obj.type_name,
            "primary_key": obj.primary_key,
            "display_name_column": obj.display_name_column,
            "dataset_name": ds.name,
            "properties": obj.properties,
            "description": obj.description,
        })
        type_names.add(obj.type_name)

    relationships: list[dict[str, Any]] = []
    if type_names:
        rels = session.execute(
            select(OntologyRelationship).where(
                OntologyRelationship.source_type.in_(type_names)
            )
        ).scalars().all()
        for r in rels:
            relationships.append({
                "source_type": r.source_type,
                "target_type": r.target_type,
                "name": r.name,
                "cardinality": r.cardinality,
                "source_key": r.source_key,
                "target_key": r.target_key,
            })

    return {"object_types": object_types, "relationships": relationships}


# --------------------------------------------------------------- entrypoint

def _register_scratch_datasets(
    session: Session, user_id: uuid.UUID | None, saved: dict[str, str]
) -> list[dict[str, str]]:
    """For each {name: parquet_path} from the sandbox, upload to object
    storage and register a new Dataset(execution_engine=duckdb)."""
    from app.connectors.parquet_upload import store_uploaded_parquet
    from app.data.models import DataSource, Dataset, DatasetColumn
    from app.platform.service import upsert_resource_sync

    created: list[dict[str, str]] = []
    for name, path in saved.items():
        try:
            with open(path, "rb") as f:
                blob = f.read()
        except OSError:
            continue
        dataset_id = uuid.uuid4()
        info = store_uploaded_parquet(blob, name, dataset_id)

        source = DataSource(
            name=f"notebook_scratch:{name}",
            source_type="notebook_scratch",
            connection_config={"saved_name": name, "storage_uri": info["storage_uri"]},
            status="ok",
            owner_id=user_id,
        )
        session.add(source)
        session.flush()

        ds = Dataset(
            id=dataset_id,
            source_id=source.id,
            name=name,
            schema_name="public",
            table_name=info["table_name"],
            ai_policy="local_only",
            execution_engine="duckdb",
            storage_uri=info["storage_uri"],
            owner_id=user_id,
        )
        session.add(ds)
        for c in info["columns"]:
            session.add(DatasetColumn(dataset_id=ds.id, name=c["name"], data_type=c["type"]))
        if user_id is not None:
            upsert_resource_sync(
                session,
                resource_type="dataset",
                object_id=ds.id,
                name=ds.name,
                owner_user_id=user_id,
                metadata={"storage_uri": ds.storage_uri, "execution_engine": ds.execution_engine},
            )
        session.flush()
        created.append({"id": str(ds.id), "name": ds.name, "storage_uri": info["storage_uri"]})
    return created


def execute_cell_in_worker(session: Session, job, input: dict[str, Any]) -> dict[str, Any]:
    from app.notebooks.sandbox import run_python

    notebook_id = uuid.UUID(input["notebook_id"])
    cell_id = uuid.UUID(input["cell_id"])
    cell_type = input.get("cell_type", "python")
    user_id = uuid.UUID(input["user_id"]) if input.get("user_id") else None
    dataset_ids = [uuid.UUID(str(value)) for value in (input.get("dataset_ids") or [])]
    parquet_dir: Path | None = None

    cell: NotebookCell | None = session.get(NotebookCell, cell_id)
    if cell is None:
        raise ValueError("cell not found")
    if cell.notebook_id != notebook_id:
        raise ValueError("cell does not belong to notebook")

    cell.last_status = "running"
    session.commit()

    try:
        code = input.get("source_snapshot", "")
        permitted_datasets = _resolve_permitted_datasets(session, dataset_ids, user_id)
        if permitted_datasets:
            parquet_dir = Path(next(iter(permitted_datasets.values()))).parent
        sandbox_result = run_python(
            code,
            permitted_datasets=permitted_datasets,
            ontology_snapshot=build_ontology_snapshot(session, dataset_ids),
            timeout_s=60,
        )

        if cell_type == "ai_prompt":
            output = {
                "generated_code": code,
                "explanation": input.get("explanation", ""),
                **sandbox_result,
            }
        else:
            output = dict(sandbox_result)

        # v0.7: register any platform_sdk.save_dataframe() outputs as new datasets.
        saved = sandbox_result.pop("saved_dataframes", None)
        if saved:
            try:
                created = _register_scratch_datasets(session, user_id, saved)
                output["created_datasets"] = created
            except Exception as e:  # noqa: BLE001
                output["save_dataframe_error"] = str(e)

        cell.last_output = output
        cell.last_status = "succeeded" if not output.get("error") else "failed"
        cell.last_run_at = datetime.utcnow()
        session.commit()
        if output.get("error"):
            raise RuntimeError(str(output["error"]))
        return output
    except Exception as e:
        session.rollback()
        cell = session.get(NotebookCell, cell_id)
        if cell is not None:
            if not cell.last_output:
                cell.last_output = {"error": str(e)}
            cell.last_status = "failed"
            cell.last_run_at = datetime.utcnow()
            session.commit()
        raise
    finally:
        if parquet_dir is not None:
            shutil.rmtree(parquet_dir, ignore_errors=True)
