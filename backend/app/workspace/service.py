import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import UserRole
from app.workspace.models import WorkspaceItem, WorkspacePermission


@dataclass
class EffectiveWorkspacePermission:
    can_view: bool = False
    can_edit: bool = False
    can_run: bool = False
    can_share: bool = False
    can_manage: bool = False

    def merge(self, p: WorkspacePermission) -> None:
        self.can_view |= bool(p.can_view)
        self.can_edit |= bool(p.can_edit)
        self.can_run |= bool(p.can_run)
        self.can_share |= bool(p.can_share)
        self.can_manage |= bool(p.can_manage)


async def ensure_root(session: AsyncSession, user_id: uuid.UUID) -> WorkspaceItem:
    rows = await session.execute(
        select(WorkspaceItem).where(
            WorkspaceItem.owner_id == user_id,
            WorkspaceItem.parent_id.is_(None),
            WorkspaceItem.item_type == "folder",
            WorkspaceItem.name == "My Workspace",
        ).order_by(WorkspaceItem.created_at, WorkspaceItem.id)
    )
    roots = list(rows.scalars().all())
    if roots:
        root = roots[0]
        for duplicate in roots[1:]:
            duplicate.parent_id = root.id
            duplicate.name = f"Recovered Workspace {str(duplicate.id)[:8]}"
        await session.flush()
        return root

    root = WorkspaceItem(name="My Workspace", item_type="folder", owner_id=user_id)
    session.add(root)
    await session.flush()
    session.add(
        WorkspacePermission(
            item_id=root.id,
            subject_type="user",
            subject_id=user_id,
            can_view=True,
            can_edit=True,
            can_run=True,
            can_share=True,
            can_manage=True,
        )
    )
    await session.flush()
    return root


async def create_linked_item(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    name: str,
    item_type: str,
    resource_type: str | None,
    resource_id: uuid.UUID | None,
    parent_id: uuid.UUID | None = None,
) -> WorkspaceItem:
    parent = await session.get(WorkspaceItem, parent_id) if parent_id else await ensure_root(session, user_id)
    item = WorkspaceItem(
        name=name,
        item_type=item_type,
        parent_id=parent.id if parent else None,
        resource_type=resource_type,
        resource_id=resource_id,
        owner_id=user_id,
    )
    session.add(item)
    await session.flush()
    session.add(
        WorkspacePermission(
            item_id=item.id,
            subject_type="user",
            subject_id=user_id,
            can_view=True,
            can_edit=True,
            can_run=True,
            can_share=True,
            can_manage=True,
        )
    )
    await session.flush()
    return item


async def _ancestor_ids(session: AsyncSession, item: WorkspaceItem) -> list[uuid.UUID]:
    out = [item.id]
    parent_id = item.parent_id
    while parent_id:
        parent = await session.get(WorkspaceItem, parent_id)
        if parent is None:
            break
        out.append(parent.id)
        parent_id = parent.parent_id
    return out


async def effective_permission(
    session: AsyncSession, user_id: uuid.UUID, item: WorkspaceItem
) -> EffectiveWorkspacePermission:
    if item.owner_id == user_id:
        return EffectiveWorkspacePermission(True, True, True, True, True)
    role_rows = await session.execute(select(UserRole.role_id).where(UserRole.user_id == user_id))
    role_ids = [r[0] for r in role_rows.all()]
    ids = await _ancestor_ids(session, item)
    rows = await session.execute(select(WorkspacePermission).where(WorkspacePermission.item_id.in_(ids)))
    eff = EffectiveWorkspacePermission()
    for p in rows.scalars().all():
        if p.subject_type == "everyone":
            eff.merge(p)
        elif p.subject_type == "user" and p.subject_id == user_id:
            eff.merge(p)
        elif p.subject_type == "role" and p.subject_id in role_ids:
            eff.merge(p)
    return eff
