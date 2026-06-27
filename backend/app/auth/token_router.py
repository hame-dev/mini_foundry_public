from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.tokens import ApiToken, ServiceAccount, new_token_secret, token_hash
from app.deps import AdminDep, CurrentUserDep, SessionDep

router = APIRouter(prefix="/auth/tokens", tags=["auth"])
admin_router = APIRouter(prefix="/admin/service-accounts", tags=["auth"])

ALLOWED_TOKEN_SCOPES = {"all", "read", "write", "admin", "query", "export", "writeback"}


class TokenCreateIn(BaseModel):
    name: str
    scopes: list[str] = []
    expires_at: datetime | None = None


class TokenCreatedOut(BaseModel):
    id: str
    name: str
    scopes: list[str]
    expires_at: datetime | None
    token: str


class ApiTokenOut(BaseModel):
    id: str
    name: str
    scopes: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ServiceAccountIn(BaseModel):
    name: str
    description: str | None = None


class ServiceAccountOut(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str | None
    is_active: bool
    created_at: datetime


def _validate_scopes(scopes: list[str]) -> list[str]:
    unknown = sorted(set(scopes) - ALLOWED_TOKEN_SCOPES)
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown token scopes: {unknown}")
    return sorted(set(scopes))


def _token_out(row: ApiToken) -> ApiTokenOut:
    return ApiTokenOut(
        id=str(row.id),
        name=row.name,
        scopes=row.scopes or [],
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


def _service_out(row: ServiceAccount) -> ServiceAccountOut:
    return ServiceAccountOut(
        id=str(row.id),
        name=row.name,
        description=row.description,
        owner_id=str(row.owner_id) if row.owner_id else None,
        is_active=row.is_active,
        created_at=row.created_at,
    )


@router.get("", response_model=list[ApiTokenOut])
async def list_tokens(session: SessionDep, user: CurrentUserDep) -> list[ApiTokenOut]:
    rows = (
        await session.execute(
            select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc())
        )
    ).scalars().all()
    return [_token_out(row) for row in rows]


@router.post("", response_model=TokenCreatedOut, status_code=201)
async def create_token(payload: TokenCreateIn, session: SessionDep, user: CurrentUserDep) -> TokenCreatedOut:
    raw = new_token_secret()
    row = ApiToken(
        user_id=user.id,
        name=payload.name,
        scopes=_validate_scopes(payload.scopes),
        expires_at=payload.expires_at,
        token_hash=token_hash(raw),
    )
    session.add(row)
    await session.commit()
    return TokenCreatedOut(id=str(row.id), name=row.name, scopes=row.scopes or [], expires_at=row.expires_at, token=raw)


@router.delete("/{token_id}")
async def revoke_token(token_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    row = await session.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "token not found")
    row.revoked_at = datetime.utcnow()
    await session.commit()
    return {"ok": True}


@admin_router.get("", response_model=list[ServiceAccountOut])
async def list_service_accounts(session: SessionDep, _: AdminDep) -> list[ServiceAccountOut]:
    rows = (await session.execute(select(ServiceAccount).order_by(ServiceAccount.created_at.desc()))).scalars().all()
    return [_service_out(row) for row in rows]


@admin_router.post("", response_model=ServiceAccountOut, status_code=201)
async def create_service_account(payload: ServiceAccountIn, session: SessionDep, admin: AdminDep) -> ServiceAccountOut:
    row = ServiceAccount(name=payload.name, description=payload.description, owner_id=admin.id)
    session.add(row)
    await session.commit()
    return _service_out(row)


@admin_router.post("/{service_account_id}/tokens", response_model=TokenCreatedOut, status_code=201)
async def create_service_account_token(
    service_account_id: uuid.UUID,
    payload: TokenCreateIn,
    session: SessionDep,
    _: AdminDep,
) -> TokenCreatedOut:
    account = await session.get(ServiceAccount, service_account_id)
    if account is None or not account.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "service account not found")
    raw = new_token_secret()
    row = ApiToken(
        service_account_id=service_account_id,
        name=payload.name,
        scopes=_validate_scopes(payload.scopes),
        expires_at=payload.expires_at,
        token_hash=token_hash(raw),
    )
    session.add(row)
    await session.commit()
    return TokenCreatedOut(id=str(row.id), name=row.name, scopes=row.scopes or [], expires_at=row.expires_at, token=raw)
