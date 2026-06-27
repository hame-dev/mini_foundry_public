import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.audit.logger import log_event
from app.auth.models import Role, User, UserRole, UserSession
from app.auth.service import assign_role, create_user, get_or_create_role, get_user_by_email
from app.deps import AdminDep, SessionDep

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


class UserAdminOut(BaseModel):
    id: str
    email: str
    name: str | None
    is_active: bool
    roles: list[str]
    created_at: datetime


class CreateUserIn(BaseModel):
    email: str
    password: str
    name: str | None = None
    roles: list[str] = []


class AssignRoleIn(BaseModel):
    user_id: uuid.UUID
    role: str


class SessionOut(BaseModel):
    id: str
    user_id: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    last_seen_at: datetime


@router.get("", response_model=list[UserAdminOut])
async def list_users(session: SessionDep, _: AdminDep) -> list[UserAdminOut]:
    users = (await session.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    role_rows = (await session.execute(
        select(UserRole.user_id, Role.name).join(Role, Role.id == UserRole.role_id)
    )).all()
    roles_by_user: dict[uuid.UUID, list[str]] = {}
    for uid, name in role_rows:
        roles_by_user.setdefault(uid, []).append(name)
    return [
        UserAdminOut(
            id=str(u.id), email=u.email, name=u.name, is_active=u.is_active,
            roles=roles_by_user.get(u.id, []), created_at=u.created_at,
        )
        for u in users
    ]


@router.post("", response_model=UserAdminOut)
async def admin_create_user(payload: CreateUserIn, session: SessionDep, _: AdminDep) -> UserAdminOut:
    if await get_user_by_email(session, payload.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    user = await create_user(session, payload.email, payload.password, payload.name)
    for r in payload.roles:
        role = await get_or_create_role(session, r)
        await assign_role(session, user.id, role.id)
    await session.commit()
    return UserAdminOut(
        id=str(user.id), email=user.email, name=user.name, is_active=user.is_active,
        roles=payload.roles, created_at=user.created_at,
    )


@router.post("/assign-role")
async def admin_assign_role(payload: AssignRoleIn, session: SessionDep, _: AdminDep) -> dict:
    user = await session.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    role = await get_or_create_role(session, payload.role)
    await assign_role(session, user.id, role.id)
    await session.commit()
    return {"ok": True}


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(session: SessionDep, _: AdminDep, active_only: bool = True) -> list[SessionOut]:
    stmt = select(UserSession).order_by(UserSession.last_seen_at.desc())
    if active_only:
        stmt = stmt.where(UserSession.revoked_at.is_(None))
    rows = (await session.execute(stmt)).scalars().all()
    return [
        SessionOut(
            id=str(s.id),
            user_id=str(s.user_id),
            expires_at=s.expires_at,
            revoked_at=s.revoked_at,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
        )
        for s in rows
    ]


@router.post("/sessions/{session_id}/revoke")
async def revoke_user_session(session_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    row = await session.get(UserSession, session_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    row.revoked_at = datetime.utcnow()
    await log_event(session, user=admin, event_type="SESSION_REVOKED", resource_type="session", resource_id=str(row.id), output_summary={"user_id": str(row.user_id)})
    await session.commit()
    return {"ok": True}
