import uuid
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock

from app.code_repo.runner import run_code_transform
from app.data.models import Dataset, DatasetColumn


@pytest.mark.asyncio
async def test_run_code_transform_success(monkeypatch):
    user_id = uuid.uuid4()
    uuid_a = uuid.uuid4()
    uuid_b = uuid.uuid4()

    # This test exercises the in-process execution path; force it on so the
    # result is deterministic regardless of whether Docker is available here.
    monkeypatch.setattr("app.notebooks.sandbox.docker_available", lambda: False)
    # In-process execution is disabled by default; opt in for this unit test.
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "allow_inprocess_code_exec", True)

    # 1. Set up mocks for pandas read/write & create_engine
    monkeypatch.setattr("app.code_repo.runner.create_engine", lambda *args, **kwargs: MagicMock())

    def mock_read_sql_query(sql, engine):
        assert "rls applied" in sql
        if "table_a" in sql:
            return pd.DataFrame([{"id": 1, "value": "A", "secret": "secret1"}])
        elif "table_b" in sql:
            return pd.DataFrame([{"id": 2, "value": "B", "secret": "secret2"}])
        return pd.DataFrame()

    monkeypatch.setattr("pandas.read_sql_query", mock_read_sql_query)

    to_sql_calls = []
    def mock_to_sql(self, name, con, schema=None, if_exists='fail', index=True, **kwargs):
        to_sql_calls.append((name, schema, self))
    monkeypatch.setattr("pandas.DataFrame.to_sql", mock_to_sql)

    # 2. Mock RLS and masking helpers
    async def mock_apply_row_policies(session, uid, sql):
        assert uid == user_id
        return sql + " -- rls applied"
    monkeypatch.setattr("app.permissions.row_policy.apply_row_policies", mock_apply_row_policies)

    async def mock_resolve_column_masks(session, uid, dataset_id):
        assert uid == user_id
        if dataset_id == uuid_a:
            return {"secret": "hidden"}
        return {}
    monkeypatch.setattr("app.permissions.masking.resolve_column_masks", mock_resolve_column_masks)

    # 3. Create mock database objects
    ds_a = Dataset(
        id=uuid_a,
        name="dataset_a",
        schema_name="public",
        table_name="table_a",
        security_markings=["PII"],
        owner_id=uuid.uuid4()
    )
    ds_b = Dataset(
        id=uuid_b,
        name="dataset_b",
        schema_name="public",
        table_name="table_b",
        security_markings=["Classified"],
        owner_id=uuid.uuid4()
    )

    # Mock execute return values:
    # 1. ds_a lookup
    res_a = MagicMock()
    res_a.scalar_one_or_none.return_value = ds_a
    # 2. ds_b lookup
    res_b = MagicMock()
    res_b.scalar_one_or_none.return_value = ds_b
    # 3. output_dataset lookup (not exists yet)
    res_out = MagicMock()
    res_out.scalar_one_or_none.return_value = None
    # 4. delete(DatasetColumn)
    res_del = MagicMock()

    session = AsyncMock()
    session.execute.side_effect = [res_a, res_b, res_out, res_del]

    # 4. Define Python files containing transform
    files = {
        "transforms.py": """
from app.code_repo.transforms import transform, Input, Output
import pandas as pd

@transform(
    Output("output_dataset"),
    input_a=Input("dataset_a"),
    input_b=Input("dataset_b")
)
def my_transform(input_a, input_b):
    # Check that input_a has secret column removed (masked)
    assert "secret" not in input_a.columns
    assert "secret" in input_b.columns
    return pd.concat([input_a, input_b], ignore_index=True)
"""
    }

    # 5. Run the transform
    res = await run_code_transform(session, user_id, files)

    assert res["status"] == "success"
    assert len(res["transforms"]) == 1
    assert res["transforms"][0]["output_dataset_name"] == "output_dataset"

    # Verify to_sql was called with the combined dataframe
    assert len(to_sql_calls) == 1
    out_table, out_schema, df_out = to_sql_calls[0]
    assert out_table == "mf_py_output_dataset"
    assert out_schema == "public"
    # Row count is 2 (1 from a + 1 from b)
    assert len(df_out) == 2

    # Verify added objects in session
    added_objects = [args[0] for args, kwargs in session.add.call_args_list]
    
    # The first added object should be the Dataset
    out_ds = next(obj for obj in added_objects if isinstance(obj, Dataset))
    assert out_ds.name == "output_dataset"
    assert set(out_ds.security_markings) == {"PII", "Classified"}
    assert out_ds.row_count == 2
    assert out_ds.owner_id == user_id

    # The columns should also be added
    cols = [obj for obj in added_objects if isinstance(obj, DatasetColumn)]
    col_names = {c.name for c in cols}
    assert col_names == {"id", "value", "secret"}
