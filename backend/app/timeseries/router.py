"""Quiver — POST /timeseries/analyze."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.data.catalog import list_visible_datasets
from app.deps import CurrentUserDep, SessionDep
from app.governed_query.service import governed_query
from app.timeseries.service import MAX_POINTS, analyze_series
from app.util.identifiers import assert_safe_ident

router = APIRouter(prefix="/timeseries", tags=["timeseries"])


class AnalyzeIn(BaseModel):
    dataset_id: uuid.UUID
    time_column: str
    value_column: str
    operations: list[str] | None = None
    resample_freq: str | None = None  # pandas offset alias, e.g. "D", "W", "H"
    rolling_window: int = 7


def _q(ident: str) -> str:
    assert_safe_ident(ident)
    return f'"{ident}"'


def _table_ref(ds) -> str:
    """Engine-appropriate FROM target: DuckDB views are bare table names;
    Postgres datasets are schema-qualified."""
    engine = getattr(ds, "execution_engine", None) or "postgres"
    if engine == "duckdb":
        return _q(ds.table_name)
    return f"{_q(ds.schema_name)}.{_q(ds.table_name)}"


@router.post("/analyze")
async def analyze(payload: AnalyzeIn, session: SessionDep, user: CurrentUserDep) -> dict:
    visible = await list_visible_datasets(session, user.id)
    ds = next((d for d in visible if d.id == payload.dataset_id), None)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dataset not found or not accessible")

    time_col = _q(payload.time_column)
    value_col = _q(payload.value_column)
    sql = (
        f"SELECT {time_col}, {value_col} FROM {_table_ref(ds)} "
        f"WHERE {time_col} IS NOT NULL AND {value_col} IS NOT NULL "
        f"ORDER BY {time_col} LIMIT {MAX_POINTS}"
    )

    try:
        result = await governed_query(
            session,
            user,
            sql,
            dataset_ids=[ds.id],
            capability="view_data",
            audit_resource_type="timeseries_analysis",
            audit_resource_id=str(ds.id),
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"query failed: {e}")

    try:
        analysis = analyze_series(
            result["rows"],
            payload.time_column,
            payload.value_column,
            operations=payload.operations,
            resample_freq=payload.resample_freq,
            rolling_window=payload.rolling_window,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    analysis["dataset_id"] = str(ds.id)
    analysis["dataset_name"] = ds.name
    return analysis
