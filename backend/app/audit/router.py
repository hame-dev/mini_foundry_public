import csv
import io
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from app.audit.models import AuditLog
from app.config import get_settings
from app.deps import AdminDep, SessionDep

router = APIRouter(prefix="/admin/audit", tags=["audit"])


class AuditLogOut(BaseModel):
    id: str
    user_id: str | None
    event_type: str
    resource_type: str | None
    resource_id: str | None
    provider: str | None
    input_summary: dict | None
    output_summary: dict | None
    created_at: datetime


class AuditRetentionOut(BaseModel):
    retention_days: int
    cutoff: datetime
    purgeable_count: int


@router.get("", response_model=list[AuditLogOut])
async def list_logs(session: SessionDep, _: AdminDep, limit: int = 200) -> list[AuditLogOut]:
    result = await session.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    )
    return [
        AuditLogOut(
            id=str(row.id),
            user_id=str(row.user_id) if row.user_id else None,
            event_type=row.event_type,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            provider=row.provider,
            input_summary=row.input_summary,
            output_summary=row.output_summary,
            created_at=row.created_at,
        )
        for row in result.scalars().all()
    ]


@router.get("/retention", response_model=AuditRetentionOut)
async def audit_retention(session: SessionDep, _: AdminDep) -> AuditRetentionOut:
    days = max(1, get_settings().audit_retention_days)
    cutoff = datetime.utcnow() - timedelta(days=days)
    count = (
        await session.execute(select(func.count()).select_from(AuditLog).where(AuditLog.created_at < cutoff))
    ).scalar() or 0
    return AuditRetentionOut(retention_days=days, cutoff=cutoff, purgeable_count=int(count))


@router.post("/retention/purge", response_model=AuditRetentionOut)
async def purge_audit_retention(session: SessionDep, _: AdminDep) -> AuditRetentionOut:
    snapshot = await audit_retention(session, _)
    await session.execute(delete(AuditLog).where(AuditLog.created_at < snapshot.cutoff))
    await session.commit()
    return await audit_retention(session, _)


@router.get("/export")
async def export_audit_logs(
    session: SessionDep,
    _: AdminDep,
    format: str = Query(default="csv", pattern="^(csv|jsonl)$"),
    limit: int = Query(default=10000, ge=1, le=100000),
) -> StreamingResponse:
    rows = (
        await session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    ).scalars().all()
    if format == "jsonl":
        content = "\n".join(
            json.dumps(
                {
                    "id": str(row.id),
                    "user_id": str(row.user_id) if row.user_id else None,
                    "event_type": row.event_type,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "provider": row.provider,
                    "input_summary": row.input_summary,
                    "output_summary": row.output_summary,
                    "ip_address": row.ip_address,
                    "created_at": row.created_at.isoformat(),
                },
                default=str,
            )
            for row in rows
        )
        return StreamingResponse(iter([content]), media_type="application/x-ndjson", headers={"Content-Disposition": 'attachment; filename="audit.jsonl"'})
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["id", "user_id", "event_type", "resource_type", "resource_id", "provider", "input_summary", "output_summary", "ip_address", "created_at"])
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "id": str(row.id),
            "user_id": str(row.user_id) if row.user_id else "",
            "event_type": row.event_type,
            "resource_type": row.resource_type or "",
            "resource_id": row.resource_id or "",
            "provider": row.provider or "",
            "input_summary": json.dumps(row.input_summary or {}, default=str),
            "output_summary": json.dumps(row.output_summary or {}, default=str),
            "ip_address": row.ip_address or "",
            "created_at": row.created_at.isoformat(),
        })
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="audit.csv"'})
