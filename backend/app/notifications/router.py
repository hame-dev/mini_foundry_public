from __future__ import annotations

import uuid
import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db import SessionLocal
from app.deps import CurrentUserDep, SessionDep, StreamUserDep
from app.notifications.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    topic: str
    title: str
    body: str | None
    resource_type: str | None
    resource_id: str | None
    delivery_channels: list
    delivery_status: dict
    read_at: datetime | None
    created_at: datetime


def _out(row: Notification) -> NotificationOut:
    return NotificationOut(
        id=str(row.id),
        topic=row.topic,
        title=row.title,
        body=row.body,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        delivery_channels=row.delivery_channels or [],
        delivery_status=row.delivery_status or {},
        read_at=row.read_at,
        created_at=row.created_at,
    )


@router.get("", response_model=list[NotificationOut])
async def list_notifications(session: SessionDep, user: CurrentUserDep, unread_only: bool = False, limit: int = 100) -> list[NotificationOut]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = (
        await session.execute(stmt.order_by(Notification.created_at.desc()).limit(max(1, min(limit, 500))))
    ).scalars().all()
    return [_out(row) for row in rows]


@router.get("/summary")
async def notification_summary(session: SessionDep, user: CurrentUserDep) -> dict:
    unread = (
        await session.execute(
            select(func.count()).select_from(Notification).where(
                Notification.user_id == user.id,
                Notification.read_at.is_(None),
            )
        )
    ).scalar() or 0
    return {"unread": int(unread)}


@router.get("/stream")
async def notification_stream(user: StreamUserDep, interval_seconds: float = 2.0) -> StreamingResponse:
    interval = max(1.0, min(interval_seconds, 30.0))
    user_id = user.id

    async def events():
        last_seen: datetime | None = None
        while True:
            chunks: list[str] = []
            async with SessionLocal() as stream_session:
                stmt = select(Notification).where(Notification.user_id == user_id)
                if last_seen is not None:
                    stmt = stmt.where(Notification.created_at > last_seen)
                rows = (
                    await stream_session.execute(stmt.order_by(Notification.created_at.asc()).limit(100))
                ).scalars().all()
                for row in rows:
                    last_seen = max(last_seen, row.created_at) if last_seen else row.created_at
                    chunks.append(f"event: notification\ndata: {json.dumps(_out(row).model_dump(mode='json'))}\n\n")
                unread = (
                    await stream_session.execute(
                        select(func.count()).select_from(Notification).where(
                            Notification.user_id == user_id,
                            Notification.read_at.is_(None),
                        )
                    )
                ).scalar() or 0
                chunks.append(f"event: summary\ndata: {json.dumps({'unread': int(unread)})}\n\n")
            for chunk in chunks:
                yield chunk
            await asyncio.sleep(interval)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/{notification_id}/read")
async def mark_read(notification_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> dict:
    row = await session.get(Notification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    row.read_at = datetime.utcnow()
    await session.commit()
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(session: SessionDep, user: CurrentUserDep) -> dict:
    rows = (
        await session.execute(
            select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
    ).scalars().all()
    now = datetime.utcnow()
    for row in rows:
        row.read_at = now
    await session.commit()
    return {"ok": True, "count": len(rows)}
