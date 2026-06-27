import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.auth.models import User
from app.data.models import Dataset
from app.data import router as data_router
from app.permissions.enforcement import PermissionDenied


def _dataset(dataset_id: uuid.UUID) -> Dataset:
    return Dataset(
        id=dataset_id,
        name="Customers",
        schema_name="public",
        table_name="customers",
        owner_id=uuid.uuid4(),
    )


def _column_rows(*rows: tuple[str, str]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


@pytest.mark.asyncio
async def test_explore_maps_value_error_to_400(monkeypatch):
    dataset_id = uuid.uuid4()
    session = AsyncMock()
    session.get.return_value = _dataset(dataset_id)
    session.execute.return_value = _column_rows()
    user = User(id=uuid.uuid4(), email="u@example.com", password_hash="x")

    async def allow(*args, **kwargs):
        return None

    async def fail(*args, **kwargs):
        raise ValueError("bad connector")

    monkeypatch.setattr(data_router, "require_object_capability", allow)
    monkeypatch.setattr(data_router, "governed_query", fail)

    with pytest.raises(HTTPException) as exc:
        await data_router.explore_dataset(dataset_id, data_router.ExplorePayload(steps=[]), session, user)
    assert exc.value.status_code == 400
    assert exc.value.detail == "bad connector"


@pytest.mark.asyncio
async def test_explore_maps_permission_denied_to_403(monkeypatch):
    dataset_id = uuid.uuid4()
    session = AsyncMock()
    session.get.return_value = _dataset(dataset_id)
    session.execute.return_value = _column_rows()
    user = User(id=uuid.uuid4(), email="u@example.com", password_hash="x")

    async def allow(*args, **kwargs):
        return None

    async def deny(*args, **kwargs):
        raise PermissionDenied("missing capability: view_data")

    monkeypatch.setattr(data_router, "require_object_capability", allow)
    monkeypatch.setattr(data_router, "governed_query", deny)

    with pytest.raises(HTTPException) as exc:
        await data_router.explore_dataset(dataset_id, data_router.ExplorePayload(steps=[]), session, user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_explore_rejects_unapproved_aggregate(monkeypatch):
    dataset_id = uuid.uuid4()
    session = AsyncMock()
    session.get.return_value = _dataset(dataset_id)
    session.execute.return_value = _column_rows(("id", "integer"))
    user = User(id=uuid.uuid4(), email="u@example.com", password_hash="x")

    async def allow(*args, **kwargs):
        return None

    monkeypatch.setattr(data_router, "require_object_capability", allow)

    payload = data_router.ExplorePayload(
        steps=[
            data_router.ExploreStep(
                type="aggregate",
                metrics=[{"aggregation": "pg_sleep", "column": "id", "alias": "x"}],
            )
        ]
    )
    with pytest.raises(HTTPException) as exc:
        await data_router.explore_dataset(dataset_id, payload, session, user)
    assert exc.value.status_code == 400
    assert "invalid aggregation" in str(exc.value.detail)
