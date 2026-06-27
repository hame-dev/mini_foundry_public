"""Dashboard service: CRUD + visibility filtering + per-component render.

Keeps the dashboards.layout JSONB and dashboard_components rows in sync inside
a single transaction. The layout is the source of truth for ordering and
filters; dashboard_components exists for indexed lookups and audit.
"""
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.dashboards.models import Dashboard, DashboardComponent
from app.permissions.enforcement import effective_capabilities_for_object


async def list_visible_dashboards(session: AsyncSession, user_id: uuid.UUID) -> list[Dashboard]:
    user = await session.get(User, user_id)
    if user is None:
        return []
    rows = (await session.execute(select(Dashboard).order_by(Dashboard.updated_at.desc()))).scalars().all()
    visible: list[Dashboard] = []
    for dashboard in rows:
        caps = await effective_capabilities_for_object(session, user, "dashboard", dashboard.id)
        if dashboard.owner_id == user_id or "view_metadata" in caps or "manage" in caps:
            visible.append(dashboard)

    return visible


async def get_dashboard_with_components(
    session: AsyncSession, dashboard_id: uuid.UUID
) -> tuple[Dashboard, list[DashboardComponent]] | None:
    d = await session.get(Dashboard, dashboard_id)
    if d is None:
        return None
    cmps = await session.execute(
        select(DashboardComponent).where(DashboardComponent.dashboard_id == dashboard_id)
    )
    return d, list(cmps.scalars().all())


async def can_view(session: AsyncSession, user: User, dashboard: Dashboard) -> bool:
    if dashboard.owner_id == user.id:
        return True
    caps = await effective_capabilities_for_object(session, user, "dashboard", dashboard.id)
    if "view_metadata" in caps or "manage" in caps:
        return True
    return False


async def can_edit(session: AsyncSession, user: User, dashboard: Dashboard) -> bool:
    if dashboard.owner_id == user.id:
        return True
    caps = await effective_capabilities_for_object(session, user, "dashboard", dashboard.id)
    if "edit" in caps or "manage" in caps:
        return True
    return False


async def can_manage(session: AsyncSession, user: User, dashboard: Dashboard) -> bool:
    if dashboard.owner_id == user.id:
        return True
    caps = await effective_capabilities_for_object(session, user, "dashboard", dashboard.id)
    if "manage" in caps:
        return True
    return False


async def replace_components_from_layout(
    session: AsyncSession, dashboard: Dashboard, layout: dict[str, Any]
) -> list[DashboardComponent]:
    """Drop existing rows for this dashboard and insert one row per
    component in the layout. Component IDs in the layout are preserved so
    cache keys remain stable across saves that didn't change a component.
    """
    existing = await session.execute(
        select(DashboardComponent).where(DashboardComponent.dashboard_id == dashboard.id)
    )
    for row in existing.scalars().all():
        await session.delete(row)
    await session.flush()

    components: list[DashboardComponent] = []
    for c in layout.get("components", []):
        cid = c.get("id")
        cmp = DashboardComponent(
            id=uuid.UUID(cid) if cid else uuid.uuid4(),
            dashboard_id=dashboard.id,
            component_type=c["component_type"],
            title=c.get("title"),
            position=c["position"],
            config=c.get("config", {}),
            data_binding=c.get("data_binding"),
            refresh=c.get("refresh"),
        )
        session.add(cmp)
        components.append(cmp)
    await session.flush()
    return components
