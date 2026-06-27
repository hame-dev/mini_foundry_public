"""Notebook + cell CRUD."""
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.notebooks.models import Notebook, NotebookCell
from app.permissions.enforcement import effective_capabilities_for_object


async def list_visible_notebooks(session: AsyncSession, user_id: uuid.UUID) -> list[Notebook]:
    user = await session.get(User, user_id)
    all_rows = (
        await session.execute(select(Notebook).order_by(Notebook.updated_at.desc()))
    ).scalars().all()
    visible: list[Notebook] = []
    for nb in all_rows:
        if nb.owner_id == user_id:
            visible.append(nb)
            continue
        caps = await effective_capabilities_for_object(session, user, "notebook", nb.id)
        if {"view_metadata", "manage"} & caps:
            visible.append(nb)
    return visible


async def get_cells(session: AsyncSession, notebook_id: uuid.UUID) -> list[NotebookCell]:
    rows = await session.execute(
        select(NotebookCell).where(NotebookCell.notebook_id == notebook_id).order_by(NotebookCell.position)
    )
    return list(rows.scalars().all())


async def add_cell(
    session: AsyncSession, *, notebook_id: uuid.UUID, cell_type: str, source: str = "",
    dataset_ids: list[uuid.UUID] | None = None,
) -> NotebookCell:
    existing = await get_cells(session, notebook_id)
    next_pos = (existing[-1].position + 1) if existing else 0
    cell = NotebookCell(
        notebook_id=notebook_id,
        position=next_pos,
        cell_type=cell_type,
        source=source,
        dataset_ids=dataset_ids or [],
        last_status="idle",
    )
    session.add(cell)
    await session.flush()
    return cell


async def reorder_cells(session: AsyncSession, notebook_id: uuid.UUID, ordered_ids: list[uuid.UUID]) -> None:
    cells = await get_cells(session, notebook_id)
    by_id = {c.id: c for c in cells}
    # Two-phase to avoid UNIQUE(notebook_id, position) collisions: shift all
    # to position +1000 first, then assign the final values.
    for i, cid in enumerate(ordered_ids):
        c = by_id.get(cid)
        if c is not None:
            c.position = 1000 + i
    await session.flush()
    for i, cid in enumerate(ordered_ids):
        c = by_id.get(cid)
        if c is not None:
            c.position = i
    await session.flush()
