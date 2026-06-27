"""CSV upload connector: reads an uploaded CSV into a staging table inside
the mini_foundry database itself and registers it as a Dataset.
"""
import io
import re
import uuid
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.storage.fs import default_bucket_uri
from app.storage.parquet import write_parquet


_TABLE_RE = re.compile(r"^[a-z0-9_]+$")
DATASET_SCHEMA = "mf_datasets"


def _safe_table_name(base: str, dataset_id: uuid.UUID) -> str:
    base = base.lower()
    base = re.sub(r"[^a-z0-9_]", "_", base)[:32].strip("_") or "csv"
    return f"staging_{base}_{dataset_id.hex[:8]}"


def infer_csv_schema(file_bytes: bytes, *, encoding: str | None = None, sample_rows: int = 50) -> dict[str, Any]:
    settings = get_settings()
    if len(file_bytes) > settings.max_upload_bytes:
        raise ValueError(f"file exceeds max_upload_bytes={settings.max_upload_bytes}")
    encodings = [encoding] if encoding else ["utf-8", "utf-8-sig", "latin-1"]
    last_error: Exception | None = None
    for candidate in [e for e in encodings if e]:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding=candidate, nrows=max(1, sample_rows))
            full_columns = list(pd.read_csv(io.BytesIO(file_bytes), encoding=candidate, nrows=0).columns)
            if len(full_columns) > settings.max_upload_columns:
                raise ValueError(f"file has too many columns ({len(full_columns)} > {settings.max_upload_columns})")
            columns = []
            for col in df.columns:
                series = df[col]
                columns.append({
                    "source_name": str(col),
                    "name": _normalize_column_name(str(col)),
                    "type": str(series.dtype),
                    "sample": series.dropna().head(3).tolist(),
                })
            return {
                "encoding": candidate,
                "columns": columns,
                "sample_rows": df.head(sample_rows).to_dict(orient="records"),
                "column_count": len(full_columns),
                "wide_file": len(full_columns) > 200,
            }
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise ValueError("unable to infer CSV schema")


def _normalize_column_name(col: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", col.strip()).strip("_").lower() or "column"


def load_csv_into_staging(file_bytes: bytes, dataset_name: str, dataset_id: uuid.UUID, *, encoding: str | None = None) -> dict[str, Any]:
    """Parse CSV bytes, write to staging table in mini_foundry DB.

    Returns {"table_name": str, "row_count": int, "columns": [{"name", "type", "sample"}]}.
    """
    settings = get_settings()
    if len(file_bytes) > settings.max_upload_bytes:
        raise ValueError(f"file exceeds max_upload_bytes={settings.max_upload_bytes}")
    inferred = infer_csv_schema(file_bytes, encoding=encoding)
    df = pd.read_csv(io.BytesIO(file_bytes), encoding=inferred["encoding"])
    if len(df.columns) > settings.max_upload_columns:
        raise ValueError(f"file has too many columns ({len(df.columns)} > {settings.max_upload_columns})")
    normalized: list[str] = []
    seen: dict[str, int] = {}
    for col in df.columns:
        base = _normalize_column_name(str(col))
        count = seen.get(base, 0)
        seen[base] = count + 1
        normalized.append(base if count == 0 else f"{base}_{count + 1}")
    df.columns = normalized
    table = _safe_table_name(dataset_name, dataset_id)
    if not _TABLE_RE.match(table):
        raise ValueError(f"unsafe table name: {table}")

    engine = create_engine(get_settings().sync_database_url)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{DATASET_SCHEMA}"'))
    df.to_sql(table, engine, schema=DATASET_SCHEMA, if_exists="replace", index=False)
    storage_uri = default_bucket_uri(f"datasets/{dataset_id.hex}/canonical/v1/data.parquet")
    write_parquet(df, storage_uri)

    columns: list[dict[str, Any]] = []
    for col in df.columns:
        series = df[col]
        sample = series.dropna().head(3).tolist()
        columns.append({"name": str(col), "type": str(series.dtype), "sample": sample})

    return {
        "schema_name": DATASET_SCHEMA,
        "table_name": table,
        "row_count": int(len(df)),
        "columns": columns,
        "storage_uri": storage_uri,
        "file_count": 1,
        "encoding": inferred["encoding"],
    }
