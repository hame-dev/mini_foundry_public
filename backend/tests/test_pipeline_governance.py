import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.permissions.enforcement import PermissionDenied
from app.pipelines.compiler import CompiledPipeline
from app.pipelines.service import PipelineServiceError, _preview_compiled_governed


@pytest.mark.asyncio
async def test_preview_compiled_governed_denies_without_permission(monkeypatch):
    user = MagicMock()
    user.id = uuid.uuid4()
    session = AsyncMock()
    compiled = CompiledPipeline(
        sql="SELECT * FROM customers",
        dataset_ids=[uuid.uuid4()],
        output_columns=["id"],
        output_name="out",
        output_description=None,
        output_node_id="out_1",
    )
    datasets = [MagicMock(id=compiled.dataset_ids[0], name="customers", owner_id=uuid.uuid4())]

    async def deny(*args, **kwargs):
        raise PermissionDenied("missing can_use_in_sql on dataset customers")

    monkeypatch.setattr("app.pipelines.service._check_inputs_readable", deny)

    with pytest.raises(PipelineServiceError, match="missing can_use_in_sql"):
        await _preview_compiled_governed(session, user, compiled, datasets, limit=10)


@pytest.mark.asyncio
async def test_preview_compiled_governed_uses_governed_query(monkeypatch):
    user = MagicMock()
    user.id = uuid.uuid4()
    session = AsyncMock()
    dataset_id = uuid.uuid4()
    compiled = CompiledPipeline(
        sql="SELECT id FROM customers",
        dataset_ids=[dataset_id],
        output_columns=["id"],
        output_name="out",
        output_description=None,
        output_node_id="out_1",
    )
    datasets = [MagicMock(id=dataset_id, name="customers", owner_id=user.id)]

    monkeypatch.setattr("app.pipelines.service._check_inputs_readable", AsyncMock())
    governed = AsyncMock(
        return_value={"columns": ["id"], "rows": [{"id": 1}], "row_count": 1}
    )
    monkeypatch.setattr("app.pipelines.service.governed_query", governed)

    result = await _preview_compiled_governed(session, user, compiled, datasets, limit=25)

    assert result["columns"] == ["id"]
    assert result["rows"] == [{"id": 1}]
    governed.assert_awaited_once()
    call_kwargs = governed.await_args.kwargs
    assert call_kwargs["dataset_ids"] == [dataset_id]
    assert "LIMIT 25" in governed.await_args.args[2]
