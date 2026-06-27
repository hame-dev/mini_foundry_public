from __future__ import annotations

import base64
import hashlib
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.logger import log_event
from app.auth.models import OidcLoginState, User
from app.auth.security import hash_password
from app.auth.service import (
    assign_role,
    create_session,
    get_or_create_role,
    get_user_by_email,
    split_setting_list,
)
from app.config import get_settings
from app.deps import get_session

router = APIRouter(prefix="/auth/sso", tags=["auth"])

OIDC_STATE_COOKIE = "mf_oidc_state"
OIDC_STATE_TTL_MINUTES = 10


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _base64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _set_cookie(response: Response, name: str, value: str, *, httponly: bool = True, max_age: int | None = None) -> None:
    settings = get_settings()
    response.set_cookie(
        name,
        value,
        httponly=httponly,
        secure=settings.environment != "development",
        samesite="lax",
        max_age=max_age,
        path="/",
    )


def _set_session_cookies(response: Response, raw_token: str, csrf_token: str) -> None:
    settings = get_settings()
    max_age = settings.session_expires_hours * 3600
    _set_cookie(response, settings.session_cookie_name, raw_token, httponly=True, max_age=max_age)
    _set_cookie(response, settings.csrf_cookie_name, csrf_token, httponly=False, max_age=max_age)


def _configured_redirect_uri() -> str:
    settings = get_settings()
    return settings.oidc_redirect_uri or f"{settings.backend_public_origin.rstrip('/')}/api/v1/auth/sso/callback"


async def _discover() -> dict[str, Any]:
    settings = get_settings()
    if not settings.oidc_issuer or not settings.oidc_client_id:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OIDC issuer/client is not configured")
    issuer = settings.oidc_issuer.rstrip("/")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{issuer}/.well-known/openid-configuration")
        response.raise_for_status()
        config = response.json()
    required = ["authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"]
    missing = [field for field in required if not config.get(field)]
    if missing:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"OIDC discovery missing: {', '.join(missing)}")
    if str(config["issuer"]).rstrip("/") != issuer:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "OIDC discovery issuer mismatch")
    return config


async def _fetch_jwks(jwks_uri: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(jwks_uri)
        response.raise_for_status()
        return response.json()


def _select_jwk(id_token: str, jwks: dict[str, Any]) -> dict[str, Any]:
    header = jwt.get_unverified_header(id_token)
    kid = header.get("kid")
    alg = header.get("alg")
    if not alg or alg == "none":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC token uses an unsafe algorithm")
    for key in jwks.get("keys", []):
        if not kid or key.get("kid") == kid:
            return key
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC signing key not found")


async def _exchange_code(discovery: dict[str, Any], state_row: OidcLoginState, code: str) -> dict[str, Any]:
    settings = get_settings()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": state_row.redirect_uri,
        "client_id": settings.oidc_client_id,
        "code_verifier": state_row.code_verifier,
    }
    auth = None
    if settings.oidc_client_secret:
        auth = (settings.oidc_client_id, settings.oidc_client_secret)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(discovery["token_endpoint"], data=data, auth=auth)
        response.raise_for_status()
        return response.json()


def _roles_from_claims(claims: dict[str, Any]) -> list[str]:
    settings = get_settings()
    roles = set(split_setting_list(settings.oidc_default_roles))
    for claim_name in (settings.oidc_role_claim, settings.oidc_group_claim):
        value = claims.get(claim_name)
        if isinstance(value, str):
            roles.add(value)
        elif isinstance(value, list):
            roles.update(str(item) for item in value if item)
    return sorted(roles)


async def _get_or_create_oidc_user(session: AsyncSession, claims: dict[str, Any]) -> User:
    email = claims.get("email")
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC token has no email claim")
    settings = get_settings()
    if settings.oidc_require_email_verified and claims.get("email_verified") is not True:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC email is not verified")

    user = await get_user_by_email(session, str(email).lower())
    if user is None:
        user = User(
            email=str(email).lower(),
            name=claims.get("name") or claims.get("preferred_username") or str(email).split("@", 1)[0],
            password_hash=hash_password(secrets.token_urlsafe(48)),
        )
        session.add(user)
        await session.flush()
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user disabled")
    for role_name in _roles_from_claims(claims):
        role = await get_or_create_role(session, role_name)
        await assign_role(session, user.id, role.id)
    return user


@router.get("/login")
async def sso_login(response: Response, session: AsyncSession = Depends(get_session)) -> dict:
    """Start a real OIDC authorization-code flow with PKCE, state, and nonce."""
    settings = get_settings()
    if not settings.oidc_issuer:
        if settings.environment != "development":
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OIDC issuer is not configured")
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "development SSO simulation has been removed; configure OIDC_ISSUER")
    discovery = await _discover()

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    redirect_uri = _configured_redirect_uri()
    session.add(
        OidcLoginState(
            state_hash=_hash_token(state),
            nonce_hash=_hash_token(nonce),
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            issuer=settings.oidc_issuer.rstrip("/"),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=OIDC_STATE_TTL_MINUTES),
        )
    )
    await session.commit()

    params = {
        "client_id": settings.oidc_client_id,
        "response_type": "code",
        "scope": settings.oidc_scopes,
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": _base64url_sha256(code_verifier),
        "code_challenge_method": "S256",
    }
    _set_cookie(response, OIDC_STATE_COOKIE, state, httponly=True, max_age=OIDC_STATE_TTL_MINUTES * 60)
    return {"authorization_url": f"{discovery['authorization_endpoint']}?{urllib.parse.urlencode(params)}"}


@router.get("/callback")
async def sso_callback(
    request: Request,
    code: str,
    state: str,
    session: AsyncSession = Depends(get_session),
):
    """Exchange OIDC code, validate JWKS signature, issuer, audience, state, and nonce."""
    settings = get_settings()
    cookie_state = request.cookies.get(OIDC_STATE_COOKIE)
    if not cookie_state or not secrets.compare_digest(cookie_state, state):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC state cookie mismatch")
    state_row = (
        await session.execute(select(OidcLoginState).where(OidcLoginState.state_hash == _hash_token(state)))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if state_row is None or state_row.consumed_at is not None or state_row.expires_at <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC state is invalid or expired")

    discovery = await _discover()
    tokens = await _exchange_code(discovery, state_row, code)
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC token response has no ID token")
    jwk = _select_jwk(id_token, await _fetch_jwks(discovery["jwks_uri"]))
    try:
        claims = jwt.decode(
            id_token,
            jwk,
            algorithms=[jwk.get("alg", jwt.get_unverified_header(id_token).get("alg"))],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer.rstrip("/"),
        )
    except JWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"OIDC token validation failed: {e}") from e
    if _hash_token(str(claims.get("nonce", ""))) != state_row.nonce_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "OIDC nonce mismatch")

    state_row.consumed_at = now
    user = await _get_or_create_oidc_user(session, claims)
    raw_token, user_session = await create_session(session, user.id)
    await log_event(
        session,
        user=user,
        event_type="LOGIN_SUCCESS",
        resource_type="session",
        resource_id=str(user_session.id),
        input_summary={"method": "oidc", "issuer": settings.oidc_issuer.rstrip("/")},
    )
    await session.commit()

    redirect = RedirectResponse(settings.frontend_origin.rstrip("/") + "/workspace", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookies(redirect, raw_token, user_session.csrf_token)
    redirect.delete_cookie(OIDC_STATE_COOKIE, path="/")
    return redirect
