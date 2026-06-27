"""Parquet upload connector. Writes a single uploaded .parquet to the
configured object store and returns the URI + a column list.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from typing import Any

from app.storage.fs import default_bucket_uri
from app.storage.parquet import parquet_schema, upload_local_to_uri


def _safe_name(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9_]", "_", name.lower())[:48].strip("_") or "parquet"


def store_uploaded_parquet(
    file_bytes: bytes, dataset_name: str, dataset_id: uuid.UUID,
) -> dict[str, Any]:
    """Persist `file_bytes` to object storage; return {storage_uri, columns,
    table_name, row_count_estimate}.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
    try:
        tmp.write(file_bytes)
        tmp.flush()
        tmp.close()

        path = f"datasets/{dataset_id.hex}.parquet"
        uri = default_bucket_uri(path)
        upload_local_to_uri(tmp.name, uri)

        cols = parquet_schema(uri)
        table_name = _safe_name(dataset_name) + "_" + dataset_id.hex[:8]
        return {
            "storage_uri": uri,
            "table_name": table_name,
            "columns": [{"name": n, "type": t} for n, t in cols],
        }
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
