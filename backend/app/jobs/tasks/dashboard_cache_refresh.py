"""Periodic warm-up of dashboard component caches."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select

from app.auth.models import User
from app.db import SessionLocal
from app.dashboards.models import Dashboard
from app.dashboards.router import _render_one
from app.jobs.registry import job_task
from app.permissions.enforcement import get_permission_version


@job_task("dashboard_cache_refresh")
def run(session, job, input: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_warm_dashboards(input))


async def _warm_dashboards(input: dict[str, Any]) -> dict[str, Any]:
    dashboard_id = input.get("dashboard_id")
    limit = max(1, min(int(input.get("limit", 100)), 500))
    filters = input.get("filters") or {}

    async with SessionLocal() as session:
        stmt = select(Dashboard).order_by(Dashboard.updated_at.desc()).limit(limit)
        if dashboard_id:
            stmt = select(Dashboard).where(Dashboard.id == uuid.UUID(str(dashboard_id)))
        dashboards = list((await session.execute(stmt)).scalars().all())
        permission_version = await get_permission_version(session)

        warmed = 0
        errors: list[dict[str, str]] = []
        for dashboard in dashboards:
            if dashboard.owner_id is None:
                errors.append({"dashboard_id": str(dashboard.id), "error": "dashboard has no owner"})
                continue
            owner = await session.get(User, dashboard.owner_id)
            if owner is None:
                errors.append({"dashboard_id": str(dashboard.id), "error": "owner not found"})
                continue
            from app.dashboards import service
            got = await service.get_dashboard_with_components(session, dashboard.id)
            if got is None:
                continue
            _, components = got
            for component in components:
                result = await _render_one(session, owner, dashboard.id, component, filters, permission_version)
                if result.status in {"ok", "cached"}:
                    warmed += 1
                else:
                    errors.append({
                        "dashboard_id": str(dashboard.id),
                        "component_id": result.id,
                        "error": result.error or result.status,
                    })

        return {
            "dashboards_seen": len(dashboards),
            "warmed": warmed,
            "errors": errors[:25],
            "error_count": len(errors),
        }
