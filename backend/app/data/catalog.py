import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.data.models import Dataset, DatasetColumn, DatasetProfile
from app.permissions.enforcement import effective_capabilities_for_object


async def list_visible_datasets(session: AsyncSession, user_id: uuid.UUID) -> list[Dataset]:
    user = await session.get(User, user_id)
    if user is None:
        return []
    all_rows = (await session.execute(select(Dataset).order_by(Dataset.name))).scalars().all()
    visible: list[Dataset] = []
    for dataset in all_rows:
        caps = await effective_capabilities_for_object(session, user, "dataset", dataset.id)
        if dataset.owner_id == user_id or "view_metadata" in caps or "manage" in caps:
            visible.append(dataset)

    return visible


async def get_columns(session: AsyncSession, dataset_id: uuid.UUID) -> list[DatasetColumn]:
    result = await session.execute(
        select(DatasetColumn).where(DatasetColumn.dataset_id == dataset_id).order_by(DatasetColumn.name)
    )
    return list(result.scalars().all())


async def get_latest_profile(session: AsyncSession, dataset_id: uuid.UUID) -> DatasetProfile | None:
    result = await session.execute(
        select(DatasetProfile)
        .where(DatasetProfile.dataset_id == dataset_id)
        .order_by(DatasetProfile.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
