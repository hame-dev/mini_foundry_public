from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from app.deps import CurrentUserDep, SessionDep
from app.media.models import MediaSet, MediaSetVersion
from app.platform.service import upsert_resource
from app.storage.fs import default_bucket_uri, get_fs

router = APIRouter(prefix="/media-sets", tags=["media"])


class MediaSetOut(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str | None
    created_at: datetime
    updated_at: datetime


class MediaVersionOut(BaseModel):
    id: str
    media_set_id: str
    version_number: int
    storage_uri: str
    file_name: str
    content_type: str | None
    size_bytes: int
    ontology_links: list
    created_at: datetime


def _set_out(row: MediaSet) -> MediaSetOut:
    return MediaSetOut(
        id=str(row.id),
        name=row.name,
        description=row.description,
        owner_id=str(row.owner_id) if row.owner_id else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _version_out(row: MediaSetVersion) -> MediaVersionOut:
    return MediaVersionOut(
        id=str(row.id),
        media_set_id=str(row.media_set_id),
        version_number=row.version_number,
        storage_uri=row.storage_uri,
        file_name=row.file_name,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        ontology_links=row.ontology_links or [],
        created_at=row.created_at,
    )


@router.get("", response_model=list[MediaSetOut])
async def list_media_sets(session: SessionDep, user: CurrentUserDep) -> list[MediaSetOut]:
    rows = (
        await session.execute(select(MediaSet).where(MediaSet.owner_id == user.id).order_by(MediaSet.updated_at.desc()))
    ).scalars().all()
    return [_set_out(row) for row in rows]


@router.post("", response_model=MediaSetOut, status_code=201)
async def create_media_set(
    session: SessionDep,
    user: CurrentUserDep,
    name: str = Form(...),
    description: str | None = Form(None),
) -> MediaSetOut:
    row = MediaSet(name=name, description=description, owner_id=user.id)
    session.add(row)
    await session.flush()
    await upsert_resource(
        session,
        resource_type="media_set",
        object_id=row.id,
        name=row.name,
        owner_user_id=user.id,
        metadata={"description": row.description},
    )
    await session.commit()
    return _set_out(row)


@router.post("/{media_set_id}/versions", response_model=MediaVersionOut, status_code=201)
async def upload_media_version(
    media_set_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
    file: UploadFile = File(...),
    ontology_links_json: str = Form("[]"),
) -> MediaVersionOut:
    media_set = await session.get(MediaSet, media_set_id)
    if media_set is None or media_set.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "media set not found")
    content = await file.read()
    version_number = int(
        (
            await session.execute(
                select(func.coalesce(func.max(MediaSetVersion.version_number), 0)).where(MediaSetVersion.media_set_id == media_set_id)
            )
        ).scalar() or 0
    ) + 1
    uri = default_bucket_uri(f"media_sets/{media_set_id}/v{version_number}/{file.filename}")
    fs = get_fs(uri)
    parent = uri.rsplit("/", 1)[0]
    if parent and not fs.exists(parent):
        fs.makedirs(parent, exist_ok=True)
    with fs.open(uri, "wb") as handle:
        handle.write(content)
    import json

    row = MediaSetVersion(
        media_set_id=media_set_id,
        version_number=version_number,
        storage_uri=uri,
        file_name=file.filename or "upload",
        content_type=file.content_type,
        size_bytes=len(content),
        ontology_links=json.loads(ontology_links_json or "[]"),
        created_by=user.id,
    )
    media_set.updated_at = datetime.utcnow()
    session.add(row)
    await session.commit()
    return _version_out(row)


@router.get("/{media_set_id}/versions", response_model=list[MediaVersionOut])
async def list_versions(media_set_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> list[MediaVersionOut]:
    media_set = await session.get(MediaSet, media_set_id)
    if media_set is None or media_set.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "media set not found")
    rows = (
        await session.execute(
            select(MediaSetVersion).where(MediaSetVersion.media_set_id == media_set_id).order_by(MediaSetVersion.version_number.desc())
        )
    ).scalars().all()
    return [_version_out(row) for row in rows]


@router.get("/{media_set_id}/versions/{version_id}/download")
async def download_media(media_set_id: uuid.UUID, version_id: uuid.UUID, session: SessionDep, user: CurrentUserDep):
    media_set = await session.get(MediaSet, media_set_id)
    row = await session.get(MediaSetVersion, version_id)
    if media_set is None or media_set.owner_id != user.id or row is None or row.media_set_id != media_set_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "media version not found")
    fs = get_fs(row.storage_uri)

    def _iter():
        with fs.open(row.storage_uri, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _iter(),
        media_type=row.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{row.file_name}"'},
    )
