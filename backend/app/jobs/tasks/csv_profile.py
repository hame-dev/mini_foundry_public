"""Background CSV profiling task.

Runs after `connectors/router.py::upload_csv` has loaded the CSV into a
staging table. Profiles the staging table and writes a DatasetProfile row.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.data.models import Dataset, DatasetProfile
from app.data.profiling import profile_local_table
from app.jobs.registry import job_task


@job_task("csv_profile")
def run(session, job, input: dict[str, Any]) -> dict[str, Any]:
    dataset_id = uuid.UUID(input["dataset_id"])
    schema = input.get("schema", "public")
    table = input["table_name"]

    profile = profile_local_table(schema, table)
    ds = session.get(Dataset, dataset_id)
    version_id = getattr(ds, "current_version_id", None) if ds else None
    session.add(DatasetProfile(dataset_id=dataset_id, dataset_version_id=version_id, profile=profile))
    return {"row_count": profile.get("row_count"), "columns": list(profile.get("columns", {}).keys())}
