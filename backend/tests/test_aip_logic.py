import uuid
import pytest
from unittest.mock import AsyncMock
from fastapi import HTTPException

from app.ai.router import run_aip_logic, AIPLogicPayload, LogicStep
from app.permissions.enforcement import PermissionDenied
from app.auth.models import User


@pytest.mark.asyncio
async def test_run_aip_logic_sql_success(monkeypatch):
    """The SQL step routes through the governed query service, and the masked
    columns/rows it returns are mapped into the step context."""
    user = User(id=uuid.uuid4(), email="test@example.com")

    monkeypatch.setattr("app.governance.service.track_usage", AsyncMock())

    async def mock_governed_query(session, u, sql, *, capability, audit_resource_type, **kwargs):
        assert u is user
        assert capability == "use_with_ai"
        assert audit_resource_type == "ai_logic"
        # secret_col already stripped by governed_query masking
        return {"columns": ["id", "name"], "rows": [{"id": 1, "name": "Alice"}], "row_count": 1}

    monkeypatch.setattr("app.ai.router.governed_query", mock_governed_query)

    session = AsyncMock()
    step = LogicStep(type="sql", query="SELECT * FROM my_table", output_var="sql_res")
    payload = AIPLogicPayload(inputs={}, steps=[step])

    res_logic = await run_aip_logic(payload, session, user)

    assert res_logic["status"] == "success"
    assert res_logic["context"]["steps"]["sql_res"] == {
        "rows": [{"id": 1, "name": "Alice"}],
        "row_count": 1,
        "columns": ["id", "name"],
    }


@pytest.mark.asyncio
async def test_run_aip_logic_sql_permission_denied(monkeypatch):
    """A PermissionDenied raised by the governed query service surfaces as a
    400 with the step context, instead of running ungoverned SQL."""
    user = User(id=uuid.uuid4(), email="test@example.com")

    monkeypatch.setattr("app.governance.service.track_usage", AsyncMock())

    async def mock_governed_query(*args, **kwargs):
        raise PermissionDenied("missing capability: use_with_ai")

    monkeypatch.setattr("app.ai.router.governed_query", mock_governed_query)

    session = AsyncMock()
    step = LogicStep(type="sql", query="SELECT * FROM my_table", output_var="sql_res")
    payload = AIPLogicPayload(inputs={}, steps=[step])

    with pytest.raises(HTTPException) as exc_info:
        await run_aip_logic(payload, session, user)

    assert exc_info.value.status_code == 400
    assert "missing capability: use_with_ai" in exc_info.value.detail["message"]
