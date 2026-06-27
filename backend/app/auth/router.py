from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth.models import User
from app.auth.security import create_access_token, hash_password, verify_password
from app.auth.service import (
    consume_password_reset_token,
    create_password_reset_token,
    create_session,
    create_user,
    get_user_by_email,
    get_user_roles,
    login_locked_until,
    record_login_attempt,
    revoke_all_sessions_for_user,
    revoke_session,
    rotate_session,
)
from app.audit.logger import log_event
from app.notifications.service import create_notification
from app.config import get_settings
from app.deps import CurrentUserDep, SessionDep

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str
    password: str
    name: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str | None = None
    token_type: str = "cookie"
    csrf_token: str | None = None


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None
    roles: list[str]


class PasswordResetRequestIn(BaseModel):
    email: str


class PasswordResetRequestOut(BaseModel):
    ok: bool = True
    reset_token: str | None = None


class PasswordResetConfirmIn(BaseModel):
    token: str
    new_password: str


@router.post("/register", response_model=UserOut)
async def register(payload: RegisterIn, session: SessionDep) -> UserOut:
    existing = await get_user_by_email(session, payload.email)
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    user = await create_user(session, payload.email, payload.password, payload.name)
    await session.commit()
    return UserOut(id=str(user.id), email=user.email, name=user.name, roles=[])


def _set_session_cookies(response: Response, raw_token: str, csrf_token: str) -> None:
    settings = get_settings()
    secure = settings.environment != "development"
    max_age = settings.session_expires_hours * 3600
    response.set_cookie(
        settings.session_cookie_name,
        raw_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn, request: Request, response: Response, session: SessionDep) -> TokenOut:
    ip = request.client.host if request.client else None
    locked_until = await login_locked_until(session, email=payload.email, ip_address=ip)
    if locked_until is not None:
        await log_event(session, user=None, event_type="LOGIN_LOCKED", input_summary={"email": payload.email, "locked_until": locked_until.isoformat()}, ip_address=ip)
        await session.commit()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"too many failed attempts; retry after {locked_until.isoformat()}")
    user = await get_user_by_email(session, payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        await record_login_attempt(session, email=payload.email, ip_address=ip, succeeded=False)
        await log_event(session, user=None, event_type="LOGIN_FAILURE", input_summary={"email": payload.email}, ip_address=ip)
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user disabled")
    await record_login_attempt(session, email=payload.email, ip_address=ip, succeeded=True)
    raw_token, user_session = await create_session(session, user.id)
    _set_session_cookies(response, raw_token, user_session.csrf_token)
    await log_event(session, user=user, event_type="LOGIN_SUCCESS", resource_type="session", resource_id=str(user_session.id))
    await session.commit()
    token = create_access_token(str(user.id)) if get_settings().allow_bearer_auth else None
    return TokenOut(access_token=token, token_type="cookie", csrf_token=user_session.csrf_token)


@router.post("/refresh", response_model=TokenOut)
async def refresh_session(request: Request, response: Response, session: SessionDep, user: CurrentUserDep) -> TokenOut:
    settings = get_settings()
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing session")
    rotated = await rotate_session(session, raw)
    if rotated is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session")
    raw_token, user_session = rotated
    _set_session_cookies(response, raw_token, user_session.csrf_token)
    await log_event(session, user=user, event_type="SESSION_ROTATED", resource_type="session", resource_id=str(user_session.id))
    await session.commit()
    token = create_access_token(str(user.id)) if get_settings().allow_bearer_auth else None
    return TokenOut(access_token=token, token_type="cookie", csrf_token=user_session.csrf_token)


@router.post("/logout")
async def logout(request: Request, response: Response, session: SessionDep, user: CurrentUserDep) -> dict:
    settings = get_settings()
    raw = request.cookies.get(settings.session_cookie_name)
    if raw:
        await revoke_session(session, raw)
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    await log_event(session, user=user, event_type="SESSION_REVOKED", resource_type="user", resource_id=str(user.id))
    await session.commit()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(session: SessionDep, user: CurrentUserDep) -> UserOut:
    roles = await get_user_roles(session, user.id)
    return UserOut(id=str(user.id), email=user.email, name=user.name, roles=roles)


@router.post("/password-reset/request", response_model=PasswordResetRequestOut)
async def request_password_reset(payload: PasswordResetRequestIn, session: SessionDep) -> PasswordResetRequestOut:
    user = await get_user_by_email(session, payload.email)
    reset_token = None
    if user is not None and user.is_active:
        raw, row = await create_password_reset_token(session, user.id)
        reset_token = raw if get_settings().environment == "development" else None
        await create_notification(
            session,
            user_id=user.id,
            topic="password_reset",
            title="Password reset requested",
            body="A password reset was requested for your account.",
            resource_type="user",
            resource_id=str(user.id),
        )
        await log_event(session, user=user, event_type="PASSWORD_RESET_REQUESTED", resource_type="user", resource_id=str(user.id), output_summary={"token_id": str(row.id)})
    else:
        await log_event(session, user=None, event_type="PASSWORD_RESET_REQUESTED", input_summary={"email": payload.email, "matched_user": False})
    await session.commit()
    return PasswordResetRequestOut(ok=True, reset_token=reset_token)


@router.post("/password-reset/confirm")
async def confirm_password_reset(payload: PasswordResetConfirmIn, session: SessionDep) -> dict:
    if len(payload.new_password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "password must be at least 8 characters")
    token = await consume_password_reset_token(session, payload.token)
    if token is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired reset token")
    user = await session.get(User, token.user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid reset token")
    user.password_hash = hash_password(payload.new_password)
    revoked = await revoke_all_sessions_for_user(session, user.id)
    await create_notification(
        session,
        user_id=user.id,
        topic="password_reset",
        title="Password reset completed",
        body="Your password was changed and existing sessions were revoked.",
        resource_type="user",
        resource_id=str(user.id),
    )
    await log_event(session, user=user, event_type="PASSWORD_RESET_COMPLETED", resource_type="user", resource_id=str(user.id), output_summary={"revoked_sessions": revoked})
    await session.commit()
    return {"ok": True}
