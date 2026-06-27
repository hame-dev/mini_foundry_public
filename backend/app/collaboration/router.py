from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.models import User
from app.collaboration.models import ResourceComment
from app.deps import CurrentUserDep, SessionDep
from app.notifications.service import create_notification
from app.permissions.enforcement import effective_resource_capabilities
from app.platform.models import Resource

router = APIRouter(prefix="/collaboration", tags=["collaboration"])

MENTION_RE = re.compile(r"@([A-Za-z0-9_.+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})")


class CommentIn(BaseModel):
    body: str
    parent_comment_id: uuid.UUID | None = None


class CommentOut(BaseModel):
    id: str
    resource_id: str
    parent_comment_id: str | None
    author_id: str | None
    author_email: str | None = None
    body: str
    mentions: list
    status: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


def _comment_out(row: ResourceComment, author_email: str | None = None) -> CommentOut:
    return CommentOut(
        id=str(row.id),
        resource_id=str(row.resource_id),
        parent_comment_id=str(row.parent_comment_id) if row.parent_comment_id else None,
        author_id=str(row.author_id) if row.author_id else None,
        author_email=author_email,
        body=row.body,
        mentions=row.mentions or [],
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        resolved_at=row.resolved_at,
    )


async def _require_resource_visible(session: SessionDep, resource_id: uuid.UUID, user: CurrentUserDep) -> Resource:
    resource = await session.get(Resource, resource_id)
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource not found")
    caps = await effective_resource_capabilities(session, user, resource)
    if not ({"view_metadata", "view_data", "manage"} & set(caps) or resource.owner_user_id == user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing resource access")
    return resource


@router.get("/resources/{resource_id}/comments", response_model=list[CommentOut])
async def list_comments(resource_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[CommentOut]:
    await _require_resource_visible(session, resource_id, user)
    rows = (
        await session.execute(
            select(ResourceComment)
            .where(ResourceComment.resource_id == resource_id)
            .order_by(ResourceComment.created_at.asc())
        )
    ).scalars().all()
    author_ids = {row.author_id for row in rows if row.author_id}
    authors: dict[uuid.UUID, str] = {}
    if author_ids:
        user_rows = (await session.execute(select(User).where(User.id.in_(author_ids)))).scalars().all()
        authors = {user.id: user.email for user in user_rows}
    return [_comment_out(row, authors.get(row.author_id) if row.author_id else None) for row in rows]


@router.post("/resources/{resource_id}/comments", response_model=CommentOut, status_code=201)
async def create_comment(resource_id: uuid.UUID, payload: CommentIn, session: SessionDep, user: CurrentUserDep) -> CommentOut:
    resource = await _require_resource_visible(session, resource_id, user)
    body = payload.body.strip()
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "comment body is required")
    if payload.parent_comment_id:
        parent = await session.get(ResourceComment, payload.parent_comment_id)
        if parent is None or parent.resource_id != resource_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "parent comment not found")
    mentions = sorted(set(MENTION_RE.findall(body)))
    row = ResourceComment(
        resource_id=resource_id,
        parent_comment_id=payload.parent_comment_id,
        author_id=user.id,
        body=body,
        mentions=mentions,
    )
    session.add(row)
    await session.flush()
    if resource.owner_user_id and resource.owner_user_id != user.id:
        await create_notification(
            session,
            user_id=resource.owner_user_id,
            topic="comment",
            title=f"New comment on {resource.name}",
            body=body[:300],
            resource_type=resource.resource_type,
            resource_id=str(resource.id),
        )
    if mentions:
        users = (await session.execute(select(User).where(User.email.in_(mentions)))).scalars().all()
        for mentioned in users:
            if mentioned.id != user.id:
                await create_notification(
                    session,
                    user_id=mentioned.id,
                    topic="mention",
                    title=f"You were mentioned on {resource.name}",
                    body=body[:300],
                    resource_type=resource.resource_type,
                    resource_id=str(resource.id),
                )
    await session.commit()
    return _comment_out(row, user.email)


@router.post("/comments/{comment_id}/resolve", response_model=CommentOut)
async def resolve_comment(comment_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> CommentOut:
    row = await session.get(ResourceComment, comment_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "comment not found")
    await _require_resource_visible(session, row.resource_id, user)
    row.status = "resolved"
    row.resolved_at = datetime.utcnow()
    row.updated_at = row.resolved_at
    await session.commit()
    author_email = None
    if row.author_id:
        author = await session.get(User, row.author_id)
        author_email = author.email if author else None
    return _comment_out(row, author_email)
