"""Effective notebook-level permission (mirrors dashboards/permissions.py)."""
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import UserRole
from app.notebooks.models import NotebookPermission


@dataclass
class EffectiveNotebookPermission:
    can_view: bool = False
    can_edit: bool = False
    can_run: bool = False
    can_manage: bool = False

    def merge(self, other: NotebookPermission) -> None:
        self.can_view |= bool(other.can_view)
        self.can_edit |= bool(other.can_edit)
        self.can_run |= bool(other.can_run)
        self.can_manage |= bool(other.can_manage)


async def effective_notebook_permission(
    session: AsyncSession, user_id: uuid.UUID, notebook_id: uuid.UUID
) -> EffectiveNotebookPermission:
    role_ids_q = await session.execute(select(UserRole.role_id).where(UserRole.user_id == user_id))
    role_ids = [r[0] for r in role_ids_q.all()]
    subjects: list[tuple[str, uuid.UUID]] = [("user", user_id)] + [("role", rid) for rid in role_ids]

    eff = EffectiveNotebookPermission()
    for subject_type, subject_id in subjects:
        rows = await session.execute(
            select(NotebookPermission).where(
                NotebookPermission.notebook_id == notebook_id,
                NotebookPermission.subject_type == subject_type,
                NotebookPermission.subject_id == subject_id,
            )
        )
        for row in rows.scalars().all():
            eff.merge(row)
    return eff
