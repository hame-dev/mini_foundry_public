from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.auth.models import User


async def log_event(
    session: AsyncSession,
    *,
    user: User | None,
    event_type: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    provider: str | None = None,
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Insert a single audit log row. Caller is responsible for commit."""
    session.add(
        AuditLog(
            user_id=user.id if user else None,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            provider=provider,
            input_summary=input_summary,
            output_summary=output_summary,
            ip_address=ip_address,
        )
    )
