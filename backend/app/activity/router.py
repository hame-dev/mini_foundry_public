import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.activity.models import ResourceActivity
from app.deps import CurrentUserDep, SessionDep

router = APIRouter(prefix="/activity", tags=["activity"])


class ActivityIn(BaseModel):
    resource_type: str
    resource_id: uuid.UUID
    title: str
    path: str | None = None
    metadata: dict[str, Any] | None = None


class FavoriteIn(BaseModel):
    resource_type: str
    resource_id: uuid.UUID
    title: str | None = None
    path: str | None = None
    favorite: bool | None = None
    metadata: dict[str, Any] | None = None


class ActivityOut(BaseModel):
    id: str
    resource_type: str
    resource_id: str
    title: str
    path: str | None
    favorite: bool
    metadata: dict[str, Any] | None
    last_viewed_at: datetime
    created_at: datetime


def _out(row: ResourceActivity) -> ActivityOut:
    return ActivityOut(
        id=str(row.id),
        resource_type=row.resource_type,
        resource_id=str(row.resource_id),
        title=row.title,
        path=row.path,
        favorite=row.favorite,
        metadata=row.resource_metadata,
        last_viewed_at=row.last_viewed_at,
        created_at=row.created_at,
    )


async def _get_activity(session, user_id: uuid.UUID, resource_type: str, resource_id: uuid.UUID) -> ResourceActivity | None:
    row = await session.execute(
        select(ResourceActivity).where(
            ResourceActivity.user_id == user_id,
            ResourceActivity.resource_type == resource_type,
            ResourceActivity.resource_id == resource_id,
        )
    )
    return row.scalar_one_or_none()


@router.get("/recents", response_model=list[ActivityOut])
async def recents(session: SessionDep, user: CurrentUserDep, limit: int = 20) -> list[ActivityOut]:
    rows = await session.execute(
        select(ResourceActivity)
        .where(ResourceActivity.user_id == user.id)
        .order_by(ResourceActivity.last_viewed_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    return [_out(r) for r in rows.scalars().all()]


@router.get("/favorites", response_model=list[ActivityOut])
async def favorites(session: SessionDep, user: CurrentUserDep, limit: int = 100) -> list[ActivityOut]:
    rows = await session.execute(
        select(ResourceActivity)
        .where(ResourceActivity.user_id == user.id, ResourceActivity.favorite.is_(True))
        .order_by(ResourceActivity.last_viewed_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    return [_out(r) for r in rows.scalars().all()]


@router.post("/track", response_model=ActivityOut)
async def track(payload: ActivityIn, session: SessionDep, user: CurrentUserDep) -> ActivityOut:
    row = await _get_activity(session, user.id, payload.resource_type, payload.resource_id)
    now = datetime.utcnow()
    if row is None:
        row = ResourceActivity(
            user_id=user.id,
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            title=payload.title,
            path=payload.path,
            resource_metadata=payload.metadata,
            last_viewed_at=now,
        )
        session.add(row)
    else:
        row.title = payload.title
        row.path = payload.path
        row.resource_metadata = payload.metadata
        row.last_viewed_at = now
    await session.commit()
    return _out(row)


@router.post("/favorites/toggle", response_model=ActivityOut)
async def toggle_favorite(payload: FavoriteIn, session: SessionDep, user: CurrentUserDep) -> ActivityOut:
    row = await _get_activity(session, user.id, payload.resource_type, payload.resource_id)
    if row is None:
        if not payload.title:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "title is required for a new favorite")
        row = ResourceActivity(
            user_id=user.id,
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            title=payload.title,
            path=payload.path,
            resource_metadata=payload.metadata,
            favorite=True if payload.favorite is None else payload.favorite,
            last_viewed_at=datetime.utcnow(),
        )
        session.add(row)
    else:
        row.favorite = (not row.favorite) if payload.favorite is None else payload.favorite
        if payload.title:
            row.title = payload.title
        if payload.path is not None:
            row.path = payload.path
        if payload.metadata is not None:
            row.resource_metadata = payload.metadata
    await session.commit()
    return _out(row)
