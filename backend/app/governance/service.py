import time
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.governance.models import UsageMetric

async def track_usage(
    session: AsyncSession,
    user_id: Any,
    resource_type: str,
    execution_time_ms: int,
    resource_id: str | None = None
) -> UsageMetric:
    """Calculate and log usage credit consumption."""
    base_credits = 0.0
    rate = 0.0

    if resource_type == "sql":
        base_credits = 0.01
        rate = 0.0001
    elif resource_type == "pipeline":
        base_credits = 0.1
        rate = 0.0005
    elif resource_type == "ai_logic":
        base_credits = 0.5
        rate = 0.002
    else:
        base_credits = 0.05
        rate = 0.0002

    compute_credits = base_credits + (execution_time_ms * rate)

    metric = UsageMetric(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        compute_credits=compute_credits,
        execution_time_ms=execution_time_ms
    )
    session.add(metric)
    await session.flush()
    return metric
