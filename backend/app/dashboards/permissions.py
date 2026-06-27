"""Effective dashboard-level permission for a user (mirrors the dataset
permission resolver in app/permissions/enforcement.py).
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import UserRole
from app.dashboards.models import DashboardPermission


@dataclass
class EffectiveDashboardPermission:
    can_view: bool = False
    can_edit: bool = False
    can_share: bool = False
    can_manage: bool = False

    def merge(self, other: DashboardPermission) -> None:
        self.can_view |= bool(other.can_view)
        self.can_edit |= bool(other.can_edit)
        self.can_share |= bool(other.can_share)
        self.can_manage |= bool(other.can_manage)


async def effective_dashboard_permission(
    session: AsyncSession, user_id: uuid.UUID, dashboard_id: uuid.UUID
) -> EffectiveDashboardPermission:
    role_ids_q = await session.execute(select(UserRole.role_id).where(UserRole.user_id == user_id))
    role_ids = [r[0] for r in role_ids_q.all()]
    subjects: list[tuple[str, uuid.UUID]] = [("user", user_id)] + [("role", rid) for rid in role_ids]

    eff = EffectiveDashboardPermission()
    for subject_type, subject_id in subjects:
        rows = await session.execute(
            select(DashboardPermission).where(
                DashboardPermission.dashboard_id == dashboard_id,
                DashboardPermission.subject_type == subject_type,
                DashboardPermission.subject_id == subject_id,
            )
        )
        for row in rows.scalars().all():
            eff.merge(row)
    rows = await session.execute(
        select(DashboardPermission).where(
            DashboardPermission.dashboard_id == dashboard_id,
            DashboardPermission.subject_type == "everyone",
        )
    )
    for row in rows.scalars().all():
        eff.merge(row)
    return eff
