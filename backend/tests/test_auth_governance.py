import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.auth.models import PasswordResetToken, PrincipalMarking, User
from app.auth.service import consume_password_reset_token, effective_marking_names, hash_session_token


def _execute_result(*, rows=None, scalar=None, scalars=None):
    result = MagicMock()
    result.all.return_value = rows or []
    result.scalar_one_or_none.return_value = scalar
    result.scalars.return_value.all.return_value = scalars or []
    return result


@pytest.mark.asyncio
async def test_effective_marking_names_include_role_group_and_all_user_grants():
    user_id = uuid.uuid4()
    role_id = uuid.uuid4()
    group_id = uuid.uuid4()
    user = User(id=user_id, email="analyst@example.com", password_hash="x", security_markings=["USER_DIRECT"])
    session = AsyncMock()
    session.execute.side_effect = [
        _execute_result(rows=[(role_id,)]),
        _execute_result(rows=[(group_id,)]),
        _execute_result(
            scalars=[
                PrincipalMarking(principal_type="role", principal_id=role_id, marking_name="ROLE_MARKING"),
                PrincipalMarking(principal_type="group", principal_id=group_id, marking_name="GROUP_MARKING"),
                PrincipalMarking(principal_type="all_users", principal_id=None, marking_name="PUBLIC_MARKING"),
                PrincipalMarking(principal_type="group", principal_id=uuid.uuid4(), marking_name="OTHER_GROUP"),
            ]
        ),
    ]

    assert await effective_marking_names(session, user) == {
        "USER_DIRECT",
        "ROLE_MARKING",
        "GROUP_MARKING",
        "PUBLIC_MARKING",
    }


@pytest.mark.asyncio
async def test_password_reset_token_is_single_use():
    raw_token = "reset-token"
    row = PasswordResetToken(
        user_id=uuid.uuid4(),
        token_hash=hash_session_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    session = AsyncMock()
    session.execute.return_value = _execute_result(scalar=row)

    consumed = await consume_password_reset_token(session, raw_token)

    assert consumed is row
    assert row.used_at is not None
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_password_reset_token_is_rejected():
    row = PasswordResetToken(
        user_id=uuid.uuid4(),
        token_hash=hash_session_token("expired"),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    session = AsyncMock()
    session.execute.return_value = _execute_result(scalar=row)

    assert await consume_password_reset_token(session, "expired") is None
    session.flush.assert_not_awaited()
