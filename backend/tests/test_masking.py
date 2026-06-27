import uuid
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock

from app.permissions.masking import (
    apply_masks,
    apply_masks_to_df,
    resolve_column_masks,
    resolve_column_masks_sync,
)
from app.permissions.models import ColumnPermission
from app.auth.models import UserRole


def test_no_masks_returns_unchanged():
    rows = [{"a": 1, "b": "x"}]
    assert apply_masks(rows, {}) == rows


def test_hidden_column_dropped():
    out = apply_masks([{"a": 1, "secret": "x"}], {"secret": "hidden"})
    assert out == [{"a": 1}]


def test_null_mask():
    out = apply_masks([{"a": 1, "secret": "x"}], {"secret": "null"})
    assert out == [{"a": 1, "secret": None}]


def test_hash_mask_truncated():
    out = apply_masks([{"email": "abc@example.com"}], {"email": "hash"})
    assert len(out[0]["email"]) == 32


def test_partial_mask():
    out = apply_masks([{"email": "abdullrahman"}], {"email": "partial"})
    assert out[0]["email"].startswith("ab") and out[0]["email"].endswith("an") and "***" in out[0]["email"]


def test_apply_masks_to_df():
    df = pd.DataFrame([
        {"id": 1, "email": "abdullrahman", "ssn": "123-45-6789", "salary": 1000, "age": 25},
        {"id": 2, "email": "johndoe", "ssn": "987-65-4321", "salary": 2000, "age": 30}
    ])
    masks = {
        "ssn": "hidden",
        "salary": "null",
        "email": "partial",
        "age": "hash"
    }
    out_df = apply_masks_to_df(df, masks)
    
    assert "ssn" not in out_df.columns
    assert all(out_df["salary"].isna())
    assert out_df.loc[0, "email"].startswith("ab") and out_df.loc[0, "email"].endswith("an") and "***" in out_df.loc[0, "email"]
    assert len(str(out_df.loc[0, "age"])) == 32


def test_apply_masks_to_df_empty():
    df = pd.DataFrame([{"a": 1}])
    assert apply_masks_to_df(df, {}).equals(df)
    assert apply_masks_to_df(pd.DataFrame(), {"a": "hidden"}).empty


def test_resolve_column_masks_sync():
    session = MagicMock()
    user_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    role_id = uuid.uuid4()

    # Query 1: UserRole roles query
    role_query = MagicMock()
    role_query.filter.return_value.all.return_value = [(role_id,)]
    group_query = MagicMock()
    group_query.filter.return_value.all.return_value = []
    
    # Query 2 & 3: ColumnPermission query for user, then role
    user_permission = ColumnPermission(
        dataset_id=dataset_id,
        column_name="email",
        subject_type="user",
        subject_id=user_id,
        can_view=True,
        mask_type="partial"
    )
    role_permission = ColumnPermission(
        dataset_id=dataset_id,
        column_name="ssn",
        subject_type="role",
        subject_id=role_id,
        can_view=False,
        mask_type=None
    )
    
    col_query_user = MagicMock()
    col_query_user.filter.return_value.all.return_value = [user_permission]
    
    col_query_role = MagicMock()
    col_query_role.filter.return_value.all.return_value = [role_permission]
    col_query_all = MagicMock()
    col_query_all.filter.return_value.all.return_value = []

    session.query.side_effect = [role_query, group_query, col_query_user, col_query_role, col_query_all]

    masks = resolve_column_masks_sync(session, user_id, dataset_id)
    assert masks == {
        "email": "partial",
        "ssn": "hidden"
    }


@pytest.mark.asyncio
async def test_resolve_column_masks_async():
    session = AsyncMock()
    user_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    role_id = uuid.uuid4()

    # Mock execute results:
    # 1. roles_ids_q
    roles_result = MagicMock()
    roles_result.all.return_value = [(role_id,)]
    groups_result = MagicMock()
    groups_result.all.return_value = []
    
    # 2. column permission for user
    user_permission = ColumnPermission(
        dataset_id=dataset_id,
        column_name="email",
        subject_type="user",
        subject_id=user_id,
        can_view=True,
        mask_type="partial"
    )
    user_perm_result = MagicMock()
    user_perm_result.scalars.return_value.all.return_value = [user_permission]

    # 3. column permission for role
    role_permission = ColumnPermission(
        dataset_id=dataset_id,
        column_name="ssn",
        subject_type="role",
        subject_id=role_id,
        can_view=False,
        mask_type=None
    )
    role_perm_result = MagicMock()
    role_perm_result.scalars.return_value.all.return_value = [role_permission]
    all_perm_result = MagicMock()
    all_perm_result.scalars.return_value.all.return_value = []

    session.execute.side_effect = [roles_result, groups_result, user_perm_result, role_perm_result, all_perm_result]

    masks = await resolve_column_masks(session, user_id, dataset_id)
    assert masks == {
        "email": "partial",
        "ssn": "hidden"
    }
