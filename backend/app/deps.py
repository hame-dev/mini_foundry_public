import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.security import decode_access_token
from app.auth.service import get_user_by_id, get_user_roles, get_valid_session
from app.auth.tokens import ApiToken, ServiceAccount, token_active, token_hash
from app.config import get_settings
from app.db import SessionLocal, get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _required_api_scopes(request: Request) -> set[str]:
    path = request.url.path
    method = request.method.upper()
    scopes = {"read"} if method in {"GET", "HEAD", "OPTIONS"} else {"write"}
    if "/admin/" in path or path.endswith("/admin"):
        scopes.add("admin")
    if any(segment in path for segment in ("/ai", "/queries", "/governed-query")):
        scopes.add("query")
    if any(segment in path for segment in ("/platform/exports", "/exports")):
        scopes.add("export")
    if any(segment in path for segment in ("/actions", "/ontology")) and method not in {"GET", "HEAD", "OPTIONS"}:
        scopes.add("writeback")
    return scopes


async def get_current_user(
    session: SessionDep,
    request: Request,
    authorization: str | None = Header(default=None),
    mf_session: str | None = Cookie(default=None),
) -> User:
    settings = get_settings()
    raw_session = request.cookies.get(settings.session_cookie_name) or mf_session
    if raw_session:
        session_row = await get_valid_session(session, raw_session)
        if session_row is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            csrf_header = request.headers.get("x-csrf-token")
            if not csrf_header or csrf_header != session_row.csrf_token:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid csrf token")
        user_id = session_row.user_id
    else:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
        token = authorization.split(" ", 1)[1]
        if token.startswith("mfpat_"):
            token_row = (
                await session.execute(
                    select(ApiToken).where(ApiToken.token_hash == token_hash(token))
                )
            ).scalar_one_or_none()
            if token_row is None or not token_active(token_row):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api token")
            token_scopes = set(token_row.scopes or [])
            required_scopes = _required_api_scopes(request)
            if token_scopes and "all" not in token_scopes and not (token_scopes & required_scopes):
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"api token missing scope: one of {sorted(required_scopes)}")
            token_row.last_used_at = datetime.now(timezone.utc)
            if token_row.user_id is not None:
                user_id = token_row.user_id
            elif token_row.service_account_id is not None:
                account = await session.get(ServiceAccount, token_row.service_account_id)
                if account is None or not account.is_active or account.owner_id is None:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid service account token")
                user_id = account.owner_id
            else:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api token")
        else:
            if not settings.allow_bearer_auth:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing session")
            try:
                payload = decode_access_token(token)
            except ValueError:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")

            try:
                user_id = uuid.UUID(payload["sub"])
            except (KeyError, ValueError):
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token subject")

    user = await get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_stream_user(
    request: Request,
    authorization: str | None = Header(default=None),
    mf_session: str | None = Cookie(default=None),
) -> User:
    async with SessionLocal() as session:
        return await get_current_user(session, request, authorization, mf_session)


StreamUserDep = Annotated[User, Depends(get_stream_user)]


async def require_admin(session: SessionDep, user: CurrentUserDep) -> User:
    roles = await get_user_roles(session, user.id)
    if "admin" not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return user


AdminDep = Annotated[User, Depends(require_admin)]
