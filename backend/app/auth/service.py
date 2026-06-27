import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Group, GroupMember, LoginAttempt, PasswordResetToken, PrincipalMarking, Role, User, UserRole, UserSession
from app.auth.security import hash_password
from app.config import get_settings


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def create_user(session: AsyncSession, email: str, password: str, name: str | None = None) -> User:
    user = User(email=email, password_hash=hash_password(password), name=name)
    session.add(user)
    await session.flush()
    return user


async def get_or_create_role(session: AsyncSession, name: str) -> Role:
    result = await session.execute(select(Role).where(Role.name == name))
    role = result.scalar_one_or_none()
    if role is None:
        role = Role(name=name)
        session.add(role)
        await session.flush()
    return role


async def assign_role(session: AsyncSession, user_id: uuid.UUID, role_id: uuid.UUID) -> None:
    exists = await session.execute(
        select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
    )
    if exists.scalar_one_or_none() is None:
        session.add(UserRole(user_id=user_id, role_id=role_id))
        await session.flush()


async def get_user_roles(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    result = await session.execute(
        select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    )
    return [row[0] for row in result.all()]


async def _user_role_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    result = await session.execute(select(UserRole.role_id).where(UserRole.user_id == user_id))
    return [row[0] for row in result.all()]


async def get_user_group_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    result = await session.execute(select(GroupMember.group_id).where(GroupMember.user_id == user_id))
    return [row[0] for row in result.all()]


async def get_or_create_group(session: AsyncSession, name: str, description: str | None = None) -> Group:
    result = await session.execute(select(Group).where(Group.name == name))
    group = result.scalar_one_or_none()
    if group is None:
        group = Group(name=name, description=description)
        session.add(group)
        await session.flush()
    elif description is not None:
        group.description = description
    return group


async def add_group_member(session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
    exists = await session.execute(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id))
    if exists.scalar_one_or_none() is None:
        session.add(GroupMember(group_id=group_id, user_id=user_id))
        await session.flush()


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(session: AsyncSession, user_id: uuid.UUID) -> tuple[str, UserSession]:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    row = UserSession(
        user_id=user_id,
        session_hash=hash_session_token(raw_token),
        csrf_token=csrf_token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.session_expires_hours),
    )
    session.add(row)
    await session.flush()
    return raw_token, row


async def get_valid_session(session: AsyncSession, raw_token: str) -> UserSession | None:
    row = (
        await session.execute(select(UserSession).where(UserSession.session_hash == hash_session_token(raw_token)))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        return None
    row.last_seen_at = now
    return row


async def revoke_session(session: AsyncSession, raw_token: str) -> bool:
    row = await get_valid_session(session, raw_token)
    if row is None:
        return False
    row.revoked_at = datetime.now(timezone.utc)
    await session.flush()
    return True


async def revoke_all_sessions_for_user(session: AsyncSession, user_id: uuid.UUID) -> int:
    rows = (await session.execute(select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None)))).scalars().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        row.revoked_at = now
    await session.flush()
    return len(rows)


async def rotate_session(session: AsyncSession, raw_token: str) -> tuple[str, UserSession] | None:
    current = await get_valid_session(session, raw_token)
    if current is None:
        return None
    current.revoked_at = datetime.now(timezone.utc)
    return await create_session(session, current.user_id)


async def record_login_attempt(session: AsyncSession, *, email: str, ip_address: str | None, succeeded: bool) -> None:
    session.add(LoginAttempt(email=email.lower(), ip_address=ip_address, succeeded=succeeded))
    await session.flush()


async def login_locked_until(session: AsyncSession, *, email: str, ip_address: str | None) -> datetime | None:
    settings = get_settings()
    window_minutes = settings.login_lockout_window_minutes
    threshold = settings.login_lockout_attempts
    lock_minutes = settings.login_lockout_minutes
    since = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    conditions = [LoginAttempt.email == email.lower(), LoginAttempt.succeeded.is_(False), LoginAttempt.created_at >= since]
    if ip_address:
        conditions.append(LoginAttempt.ip_address == ip_address)
    count = (await session.execute(select(func.count(LoginAttempt.id)).where(*conditions))).scalar_one()
    if int(count or 0) < threshold:
        return None
    latest = (await session.execute(select(func.max(LoginAttempt.created_at)).where(*conditions))).scalar_one_or_none()
    if latest is None:
        return None
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    locked_until = latest + timedelta(minutes=lock_minutes)
    return locked_until if locked_until > datetime.now(timezone.utc) else None


async def create_password_reset_token(session: AsyncSession, user_id: uuid.UUID) -> tuple[str, PasswordResetToken]:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(48)
    row = PasswordResetToken(
        user_id=user_id,
        token_hash=hash_session_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.password_reset_expires_minutes),
    )
    session.add(row)
    await session.flush()
    return raw_token, row


async def consume_password_reset_token(session: AsyncSession, raw_token: str) -> PasswordResetToken | None:
    row = (
        await session.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_session_token(raw_token)))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None or row.used_at is not None:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires <= now:
        return None
    row.used_at = now
    await session.flush()
    return row


async def effective_marking_names(session: AsyncSession, user: User) -> set[str]:
    roles = await _user_role_ids(session, user.id)
    groups = await get_user_group_ids(session, user.id)
    subjects: list[tuple[str, uuid.UUID | None]] = [
        ("user", user.id),
        *[("role", role_id) for role_id in roles],
        *[("group", group_id) for group_id in groups],
        ("all_users", None),
    ]
    rows = (
        await session.execute(
            select(PrincipalMarking).where(
                PrincipalMarking.principal_type.in_([subject[0] for subject in subjects])
            )
        )
    ).scalars().all()
    subject_set = set(subjects)
    names = set(user.security_markings or [])
    for row in rows:
        if (row.principal_type, row.principal_id) in subject_set:
            names.add(row.marking_name)
    return names


def split_setting_list(raw: str | None) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]
