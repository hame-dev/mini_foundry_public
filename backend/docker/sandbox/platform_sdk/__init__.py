"""Mini Foundry sandbox SDK.

Available to user code running inside the sandbox container as `platform_sdk`.
Configured at sandbox boot from /workspace/ctx.json — users should not call
`configure()` themselves.

Capabilities granted to sandboxed code:
  - load_table / query    : read permitted datasets (mounted as parquet)
  - save_dataframe        : persist a result back to the platform
  - objects               : read-only ontology access (see objects.py)
  - transform/Input/Output: @transform authoring for Code Repositories
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

import pandas as pd


_PERMITTED: dict[str, str] = {}     # dataset_name -> parquet path
_DB_URL: str | None = None          # currently unused; reserved for v0.7
_SAVED: dict[str, str] = {}         # name -> /workspace/output/<safe>.parquet
_ONTOLOGY: dict[str, Any] = {}      # {"object_types": [...], "relationships": [...]}


def configure(
    *,
    db_url: str | None,
    permitted_datasets: dict[str, str],
    ontology: dict[str, Any] | None = None,
) -> None:
    global _DB_URL, _PERMITTED, _ONTOLOGY
    _DB_URL = db_url
    _PERMITTED = dict(permitted_datasets)
    _ONTOLOGY = dict(ontology or {})


def load_table(name: str, limit: int | None = None) -> pd.DataFrame:
    """Return a DataFrame for `name`. Only datasets the cell was granted
    access to are mounted; anything else raises PermissionError.
    """
    path = _PERMITTED.get(name)
    if path is None:
        allowed = sorted(_PERMITTED.keys())
        raise PermissionError(
            f"dataset {name!r} not permitted for this cell. Permitted: {allowed}"
        )
    df = pd.read_parquet(path)
    if limit is not None:
        df = df.head(limit)
    return df


def query(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    raise NotImplementedError(
        "platform_sdk.query is not available in the sandbox; use load_table() instead."
    )


def save_dataframe(df: pd.DataFrame, name: str) -> None:
    """Persist a DataFrame as a Parquet file in /workspace/output/.

    The worker (host-side) reads this directory after the sandbox exits,
    uploads each file to object storage, and registers it as a new
    duckdb-engine Dataset owned by the running user. See
    app.notebooks.execution.execute_cell_in_worker.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("save_dataframe expects a pandas DataFrame")
    safe = re.sub(r"[^a-z0-9_]", "_", name.lower())[:48].strip("_")
    if not safe:
        raise ValueError(f"invalid dataset name: {name!r}")
    output_dir = Path("/workspace/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{safe}.parquet"
    df.to_parquet(path, index=False)
    _SAVED[name] = str(path)


def saved_datasets() -> dict[str, str]:
    return dict(_SAVED)


# ---------------------------------------------------------------------------
# @transform authoring (mirror of app.code_repo.transforms so Code Repository
# transforms can run inside the sandbox identically to the host path).
# ---------------------------------------------------------------------------

class Input:
    def __init__(self, dataset_name: str):
        self.dataset_name = dataset_name


class Output:
    def __init__(self, dataset_name: str):
        self.dataset_name = dataset_name


class TransformRegistry:
    def __init__(self) -> None:
        self.transforms: list[dict[str, Any]] = []

    def register(self, inputs: dict[str, Input], output: Output, fn: Callable) -> None:
        self.transforms.append({"inputs": inputs, "output": output, "fn": fn})


registry = TransformRegistry()


def transform(output: Output, **inputs: Input):
    def decorator(fn: Callable):
        registry.register(inputs, output, fn)
        return fn
    return decorator


def _autoconfig_from_env() -> None:
    """Read MF_CTX file path and configure the SDK from it."""
    ctx_path = os.environ.get("MF_CTX")
    if ctx_path and Path(ctx_path).exists():
        ctx = json.loads(Path(ctx_path).read_text())
        configure(
            db_url=ctx.get("db_url"),
            permitted_datasets=ctx.get("permitted_datasets", {}),
            ontology=ctx.get("ontology", {}),
        )


_autoconfig_from_env()
