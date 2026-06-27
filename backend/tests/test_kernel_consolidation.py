"""Phase 1 kernel consolidation: branch-aware version/schema resolution and
immutable pipeline-input pinning."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.platform.service import effective_schema, resolve_dataset_version


class _Dataset:
    def __init__(self, *, execution_engine="postgres", branch_name="main", schema_name="public"):
        self.execution_engine = execution_engine
        self.branch_name = branch_name
        self.schema_name = schema_name


# --- Item 4: shared branch -> schema mapping --------------------------------


def test_effective_schema_main_branch_uses_dataset_schema():
    assert effective_schema(_Dataset(schema_name="mf_datasets")) == "mf_datasets"


def test_effective_schema_postgres_branch_uses_branch_schema():
    ds = _Dataset(branch_name="feature-1")
    assert effective_schema(ds) == "mf_branch_feature_1"


def test_effective_schema_branch_override_argument_wins():
    ds = _Dataset(branch_name="main")
    assert effective_schema(ds, branch_name="exp-2") == "mf_branch_exp_2"


def test_effective_schema_duckdb_ignores_branch_schema():
    ds = _Dataset(execution_engine="duckdb", branch_name="feature-1", schema_name="public")
    assert effective_schema(ds) == "public"


# --- Item 4: branch-aware version resolution --------------------------------


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_resolve_dataset_version_returns_branch_version():
    dataset_id = uuid.uuid4()
    branch_version = MagicMock(id=uuid.uuid4(), version_number=3, branch_name="feature")
    session = AsyncMock()
    session.execute.return_value = _scalar_result(branch_version)

    resolved = await resolve_dataset_version(session, dataset_id, branch_name="feature")

    assert resolved is branch_version
    session.get.assert_not_called()  # branch given -> no need to load the dataset


@pytest.mark.asyncio
async def test_resolve_dataset_version_falls_back_to_latest_when_branch_empty():
    dataset_id = uuid.uuid4()
    latest = MagicMock(id=uuid.uuid4(), version_number=9, branch_name="main")
    session = AsyncMock()
    # 1st execute: branch query -> None; 2nd execute: latest_dataset_version -> latest
    session.execute.side_effect = [_scalar_result(None), _scalar_result(latest)]

    resolved = await resolve_dataset_version(session, dataset_id, branch_name="empty-branch")

    assert resolved is latest


# --- Item 5: pipeline input pinning resolves duckdb storage overrides --------


@pytest.mark.asyncio
async def test_resolve_storage_overrides_pins_duckdb_to_version_uri():
    from app.governed_query.service import _resolve_storage_overrides

    duck_id = uuid.uuid4()
    pg_id = uuid.uuid4()
    duck_version_id = uuid.uuid4()
    pg_version_id = uuid.uuid4()

    duck_ds = MagicMock(id=duck_id, execution_engine="duckdb")
    pg_ds = MagicMock(id=pg_id, execution_engine="postgres")

    session = AsyncMock()
    session.get.return_value = MagicMock(storage_uri="s3://bucket/pinned.parquet")

    overrides = await _resolve_storage_overrides(
        session,
        [duck_ds, pg_ds],
        {duck_id: duck_version_id, pg_id: pg_version_id},
    )

    # Only the duckdb dataset is physically pinned; postgres stays live.
    assert overrides == {duck_id: "s3://bucket/pinned.parquet"}


@pytest.mark.asyncio
async def test_resolve_storage_overrides_none_when_unpinned():
    from app.governed_query.service import _resolve_storage_overrides

    session = AsyncMock()
    assert await _resolve_storage_overrides(session, [MagicMock(id=uuid.uuid4())], None) is None


# --- Item 5: duckdb runner actually reads the pinned uri --------------------


def test_run_duckdb_sql_uses_storage_override(tmp_path, monkeypatch):
    pytest.importorskip("duckdb")
    pytest.importorskip("pyarrow")
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    from app.execution.duckdb_runner import run_duckdb_sql

    monkeypatch.setenv("STORAGE_BACKEND", "local")
    from app.config import get_settings

    get_settings.cache_clear()  # type: ignore[attr-defined]

    live = tmp_path / "live.parquet"
    pinned = tmp_path / "pinned.parquet"
    pq.write_table(pa.Table.from_pandas(pd.DataFrame({"id": [1, 2, 3]})), live)
    pq.write_table(pa.Table.from_pandas(pd.DataFrame({"id": [10]})), pinned)

    ds = MagicMock(execution_engine="duckdb", table_name="rows", storage_uri=str(live), branch_name="main", source_id=None)
    ds.id = uuid.uuid4()

    result = run_duckdb_sql("SELECT COUNT(*) AS n FROM rows", [ds], storage_overrides={ds.id: str(pinned)})

    assert result["rows"][0]["n"] == 1  # pinned file has a single row, not the live three
