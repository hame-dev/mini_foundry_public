"""Parquet read/write via fsspec + pyarrow."""
from __future__ import annotations

from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from app.storage.fs import get_fs


def read_parquet(uri: str) -> pd.DataFrame:
    fs = get_fs(uri)
    with fs.open(uri, "rb") as f:
        return pq.read_table(f).to_pandas()


def write_parquet(df: pd.DataFrame, uri: str) -> None:
    fs = get_fs(uri)
    parent = uri.rsplit("/", 1)[0]
    try:
        if parent and not fs.exists(parent):
            fs.makedirs(parent, exist_ok=True)
    except Exception:
        pass
    with fs.open(uri, "wb") as f:
        df.to_parquet(f, index=False)


def upload_local_to_uri(local_path: str, uri: str) -> None:
    fs = get_fs(uri)
    parent = uri.rsplit("/", 1)[0]
    try:
        if parent and not fs.exists(parent):
            fs.makedirs(parent, exist_ok=True)
    except Exception:
        pass
    fs.put_file(local_path, uri)


def parquet_schema(uri: str) -> list[tuple[str, str]]:
    """Return [(column_name, arrow_type_str)] for the parquet at uri."""
    fs = get_fs(uri)
    with fs.open(uri, "rb") as f:
        meta = pq.read_metadata(f)
        schema = meta.schema.to_arrow_schema()
    return [(field.name, str(field.type)) for field in schema]
