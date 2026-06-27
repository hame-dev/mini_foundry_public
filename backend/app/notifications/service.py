from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import Notification


async def create_notification(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    topic: str,
    title: str,
    body: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    channels: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Notification:
    row = Notification(
        user_id=user_id,
        topic=topic,
        title=title,
        body=body,
        resource_type=resource_type,
        resource_id=resource_id,
        delivery_channels=channels or ["in_app"],
        delivery_status={"in_app": "delivered", **(metadata or {})},
    )
    session.add(row)
    await session.flush()
    return row
