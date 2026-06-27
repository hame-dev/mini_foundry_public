import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.permissions.secrets import encrypt_value, decrypt_value, create_secret, get_secret, get_secret_sync
from app.permissions.models import Secret


def test_encryption_decryption_roundtrip():
    val = "postgres-super-secret-password-123"
    enc = encrypt_value(val)
    assert enc != val
    dec = decrypt_value(enc)
    assert dec == val


@pytest.mark.asyncio
async def test_create_secret():
    session = AsyncMock()
    val = "my_password"

    secret_id = await create_secret(session, val)
    assert isinstance(secret_id, uuid.UUID) or secret_id is None
    # Verify add was called on session
    assert session.add.called
    added_obj = session.add.call_args[0][0]
    assert isinstance(added_obj, Secret)
    assert decrypt_value(added_obj.secret_value) == val


@pytest.mark.asyncio
async def test_get_secret():
    session = AsyncMock()
    secret_id = uuid.uuid4()
    encrypted = encrypt_value("secret_pass")
    mock_secret = Secret(id=secret_id, secret_value=encrypted)

    session.get.return_value = mock_secret
    val = await get_secret(session, secret_id)
    assert val == "secret_pass"
    session.get.assert_called_with(Secret, secret_id)


def test_get_secret_sync():
    session = MagicMock()
    secret_id = uuid.uuid4()
    encrypted = encrypt_value("sync_secret")
    mock_secret = Secret(id=secret_id, secret_value=encrypted)

    session.get.return_value = mock_secret
    val = get_secret_sync(session, secret_id)
    assert val == "sync_secret"
    session.get.assert_called_with(Secret, secret_id)
