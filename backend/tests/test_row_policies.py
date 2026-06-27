import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.permissions.row_policy import resolve_row_policies, apply_row_policies
from app.data.models import Dataset
from app.permissions.models import RowPolicy
from app.auth.models import UserRole


@pytest.mark.asyncio
async def test_resolve_row_policies_no_tables():
    session = AsyncMock()
    res = await resolve_row_policies(session, uuid.uuid4(), [])
    assert res == {}


@pytest.mark.asyncio
async def test_resolve_row_policies_no_datasets():
    session = AsyncMock()
    # Mocking select(Dataset) executing and returning empty list
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute.return_value = mock_result

    res = await resolve_row_policies(session, uuid.uuid4(), ["non_existent"])
    assert res == {}


@pytest.mark.asyncio
async def test_resolve_row_policies_with_matching_user_policy():
    session = AsyncMock()
    user_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    # Create mock database objects
    ds = Dataset(id=dataset_id, table_name="customers")
    role = UserRole(user_id=user_id, role_id=uuid.uuid4())
    policy = RowPolicy(dataset_id=dataset_id, subject_type="user", subject_id=user_id, sql_condition="country = 'US'")

    # Mock DB query executions sequentially
    # 1. Dataset lookup
    ds_result = MagicMock()
    ds_result.scalars.return_value.all.return_value = [ds]

    # 2. Roles lookup
    role_result = MagicMock()
    role_result.all.return_value = [(role.role_id,)]

    # 3. Group membership lookup
    group_result = MagicMock()
    group_result.all.return_value = []

    # 4. All policies lookup
    policies_result = MagicMock()
    policies_result.scalars.return_value.all.return_value = [policy]

    # Set up mock execute return values
    session.execute.side_effect = [ds_result, role_result, group_result, policies_result]

    policies = await resolve_row_policies(session, user_id, ["customers"])
    assert "customers" in policies
    assert policies["customers"] == "(country = 'US')"


@pytest.mark.asyncio
async def test_resolve_row_policies_with_non_matching_user_policy():
    session = AsyncMock()
    user_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    ds = Dataset(id=dataset_id, table_name="customers")
    role = UserRole(user_id=user_id, role_id=uuid.uuid4())
    policy = RowPolicy(dataset_id=dataset_id, subject_type="user", subject_id=uuid.uuid4(), sql_condition="country = 'US'")

    ds_result = MagicMock()
    ds_result.scalars.return_value.all.return_value = [ds]
    role_result = MagicMock()
    role_result.all.return_value = [(role.role_id,)]
    group_result = MagicMock()
    group_result.all.return_value = []
    policies_result = MagicMock()
    policies_result.scalars.return_value.all.return_value = [policy]

    session.execute.side_effect = [ds_result, role_result, group_result, policies_result]

    policies = await resolve_row_policies(session, user_id, ["customers"])
    assert "customers" in policies
    assert policies["customers"] == "FALSE"


@pytest.mark.asyncio
async def test_resolve_row_policies_matches_group_subject():
    """A policy whose subject is a group the user belongs to must apply."""
    session = AsyncMock()
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    ds = Dataset(id=dataset_id, table_name="customers")
    policy = RowPolicy(dataset_id=dataset_id, subject_type="group", subject_id=group_id, sql_condition="region = 'EMEA'")

    ds_result = MagicMock()
    ds_result.scalars.return_value.all.return_value = [ds]
    role_result = MagicMock()
    role_result.all.return_value = []
    group_result = MagicMock()
    group_result.all.return_value = [(group_id,)]
    policies_result = MagicMock()
    policies_result.scalars.return_value.all.return_value = [policy]

    session.execute.side_effect = [ds_result, role_result, group_result, policies_result]

    policies = await resolve_row_policies(session, user_id, ["customers"])
    assert policies["customers"] == "(region = 'EMEA')"


@pytest.mark.asyncio
async def test_apply_row_policies_fails_closed_on_parse_error(monkeypatch):
    """If the SQL cannot be parsed we cannot prove policies were applied, so the
    query must be rejected rather than run unfiltered."""
    from app.execution.sql_validator import SqlValidationError

    import app.permissions.row_policy

    def boom(*args, **kwargs):
        raise ValueError("cannot parse")

    monkeypatch.setattr(app.permissions.row_policy.sqlglot, "parse", boom)

    with pytest.raises(SqlValidationError):
        await apply_row_policies(AsyncMock(), uuid.uuid4(), "SELECT * FROM customers")


@pytest.mark.asyncio
async def test_apply_row_policies_rewrites_simple_query(monkeypatch):
    session = AsyncMock()
    user_id = uuid.uuid4()

    async def mock_resolve(*args, **kwargs):
        return {"customers": "country = 'US'"}

    import app.permissions.row_policy
    monkeypatch.setattr(app.permissions.row_policy, "resolve_row_policies", mock_resolve)

    sql = "SELECT * FROM customers"
    rewritten = await apply_row_policies(session, user_id, sql)
    # The rewritten query should select from subquery with condition country = 'US'
    # and retain customers as an alias
    assert "WHERE country = 'US'" in rewritten
    assert "FROM (SELECT * FROM customers WHERE country = 'US') AS customers" in rewritten


@pytest.mark.asyncio
async def test_apply_row_policies_preserves_aliases(monkeypatch):
    session = MagicMock()
    user_id = uuid.uuid4()

    async def mock_resolve(*args, **kwargs):
        return {"customers": "country = 'US'"}

    import app.permissions.row_policy
    monkeypatch.setattr(app.permissions.row_policy, "resolve_row_policies", mock_resolve)

    sql = "SELECT c.id FROM customers c JOIN orders o ON c.id = o.customer_id"
    rewritten = await apply_row_policies(session, user_id, sql)
    assert "FROM (SELECT * FROM customers WHERE country = 'US') AS c" in rewritten


def test_resolve_row_policies_sync_no_tables():
    session = MagicMock()
    from app.permissions.row_policy import resolve_row_policies_sync
    res = resolve_row_policies_sync(session, uuid.uuid4(), [])
    assert res == {}


def test_resolve_row_policies_sync_no_datasets():
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    from app.permissions.row_policy import resolve_row_policies_sync
    res = resolve_row_policies_sync(session, uuid.uuid4(), ["non_existent"])
    assert res == {}


def test_apply_row_policies_sync_rewrites_simple_query(monkeypatch):
    session = MagicMock()
    user_id = uuid.uuid4()

    def mock_resolve(*args, **kwargs):
        return {"customers": "country = 'US'"}

    import app.permissions.row_policy
    monkeypatch.setattr(app.permissions.row_policy, "resolve_row_policies_sync", mock_resolve)

    from app.permissions.row_policy import apply_row_policies_sync
    sql = "SELECT * FROM customers"
    rewritten = apply_row_policies_sync(session, user_id, sql)
    assert "WHERE country = 'US'" in rewritten
    assert "FROM (SELECT * FROM customers WHERE country = 'US') AS customers" in rewritten

