import base64
import hashlib
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.permissions.models import Secret
from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    settings = get_settings()
    # Deriving a valid 32-byte key from settings.encryption_key
    key_bytes = settings.encryption_key.encode("utf-8")
    derived_key = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
    return Fernet(derived_key)


def encrypt_value(val: str) -> str:
    f = _get_fernet()
    return f.encrypt(val.encode("utf-8")).decode("utf-8")


def decrypt_value(val: str) -> str:
    f = _get_fernet()
    return f.decrypt(val.encode("utf-8")).decode("utf-8")


def secret_manager_status() -> dict:
    settings = get_settings()
    provider = settings.secret_manager_provider.lower()
    if provider == "vault":
        configured = bool(settings.vault_addr and settings.vault_token)
        return {"provider": "vault", "configured": configured, "enabled": configured}
    if provider == "sops":
        configured = bool(settings.sops_file_path)
        return {"provider": "sops", "configured": configured, "enabled": configured}
    return {"provider": "local", "configured": True, "enabled": True}


async def create_secret(
    session: AsyncSession, val: str, *, name: str | None = None, description: str | None = None
) -> uuid.UUID:
    encrypted = encrypt_value(val)
    secret = Secret(secret_value=encrypted, name=name, description=description)
    session.add(secret)
    await session.flush()
    return secret.id


async def get_secret(session: AsyncSession, secret_id: uuid.UUID) -> str:
    secret = await session.get(Secret, secret_id)
    if secret is None:
        raise ValueError(f"secret {secret_id} not found")
    return decrypt_value(secret.secret_value)


def get_secret_sync(session, secret_id: uuid.UUID) -> str:
    """Synchronous version for use inside background tasks / execution engines."""
    secret = session.get(Secret, secret_id)
    if secret is None:
        raise ValueError(f"secret {secret_id} not found")
    return decrypt_value(secret.secret_value)


async def delete_secret(session: AsyncSession, secret_id: uuid.UUID) -> None:
    secret = await session.get(Secret, secret_id)
    if secret:
        await session.delete(secret)
        await session.flush()
