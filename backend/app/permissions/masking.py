"""Column masking applied to result rows.

Resolves ColumnPermission rows for (dataset, user+roles) and rewrites values
according to mask_type. Hidden columns are dropped entirely.
"""
import hashlib
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
import pandas as pd

from app.auth.models import GroupMember, UserRole
from app.auth.service import get_user_group_ids
from app.permissions.models import ColumnPermission


async def resolve_column_masks(
    session: AsyncSession, user_id: uuid.UUID, dataset_id: uuid.UUID
) -> dict[str, str]:
    """Return {column_name: mask_type} for columns the user must have masked."""
    role_ids_q = await session.execute(select(UserRole.role_id).where(UserRole.user_id == user_id))
    role_ids = [row[0] for row in role_ids_q.all()]
    group_ids = await get_user_group_ids(session, user_id)
    subjects = (
        [("user", user_id)]
        + [("role", rid) for rid in role_ids]
        + [("group", gid) for gid in group_ids]
        + [("all_users", None)]
    )

    masks: dict[str, str] = {}
    for subject_type, subject_id in subjects:
        result = await session.execute(
            select(ColumnPermission).where(
                ColumnPermission.dataset_id == dataset_id,
                ColumnPermission.subject_type == subject_type,
                ColumnPermission.subject_id == subject_id,
            )
        )
        for row in result.scalars().all():
            if not row.can_view:
                masks[row.column_name] = "hidden"
            elif row.mask_type and row.mask_type != "none":
                masks.setdefault(row.column_name, row.mask_type)
    return masks


def apply_masks(rows: list[dict], masks: dict[str, str]) -> list[dict]:
    if not masks:
        return rows
    out: list[dict] = []
    for row in rows:
        new = {}
        for col, val in row.items():
            mask = masks.get(col)
            if mask == "hidden":
                continue
            if mask == "null":
                new[col] = None
            elif mask == "hash" and val is not None:
                new[col] = hashlib.md5(str(val).encode()).hexdigest()
            elif mask == "partial" and isinstance(val, str) and len(val) > 4:
                new[col] = val[:2] + "***" + val[-2:]
            else:
                new[col] = val
        out.append(new)
    return out


def resolve_column_masks_sync(
    session: Session, user_id: uuid.UUID, dataset_id: uuid.UUID
) -> dict[str, str]:
    """Return {column_name: mask_type} for columns the user must have masked synchronously."""
    role_ids = [
        row[0]
        for row in session.query(UserRole.role_id)
        .filter(UserRole.user_id == user_id)
        .all()
    ]
    group_ids = [
        row[0]
        for row in session.query(GroupMember.group_id)
        .filter(GroupMember.user_id == user_id)
        .all()
    ]
    subjects = (
        [("user", user_id)]
        + [("role", rid) for rid in role_ids]
        + [("group", gid) for gid in group_ids]
        + [("all_users", None)]
    )

    masks: dict[str, str] = {}
    for subject_type, subject_id in subjects:
        rows = (
            session.query(ColumnPermission)
            .filter(
                ColumnPermission.dataset_id == dataset_id,
                ColumnPermission.subject_type == subject_type,
                ColumnPermission.subject_id == subject_id,
            )
            .all()
        )
        for row in rows:
            if not row.can_view:
                masks[row.column_name] = "hidden"
            elif row.mask_type and row.mask_type != "none":
                masks.setdefault(row.column_name, row.mask_type)
    return masks


def apply_masks_to_df(df: pd.DataFrame, masks: dict[str, str]) -> pd.DataFrame:
    """Apply column masking rules to a Pandas DataFrame."""
    if not masks or df.empty:
        return df
    # Make a copy to avoid SettingWithCopyWarning
    df = df.copy()
    for col, mask in masks.items():
        if col not in df.columns:
            continue
        if mask == "hidden":
            df.drop(columns=[col], inplace=True)
        elif mask == "null":
            df[col] = None
        elif mask == "hash":
            df[col] = df[col].apply(
                lambda x: hashlib.md5(str(x).encode()).hexdigest()
                if pd.notna(x)
                else x
            )
        elif mask == "partial":
            df[col] = df[col].apply(
                lambda x: str(x)[:2] + "***" + str(x)[-2:]
                if isinstance(x, str) and len(x) > 4
                else x
            )
    return df
