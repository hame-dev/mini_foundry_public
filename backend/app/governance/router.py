import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from app.audit.logger import log_event
from app.auth.models import Group, GroupMember, PrincipalMarking, User
from app.auth.service import add_group_member, get_or_create_group
from app.deps import AdminDep, CurrentUserDep, SessionDep
from app.governance.models import UsageMetric
from app.permissions.enforcement import bump_permission_version
from app.platform.models import Marking

router = APIRouter(prefix="/governance", tags=["governance"])


class GroupIn(BaseModel):
    name: str
    description: str | None = None


class GroupOut(BaseModel):
    id: str
    name: str
    description: str | None
    member_count: int = 0
    created_at: datetime


class GroupMemberIn(BaseModel):
    user_id: uuid.UUID


class MarkingIn(BaseModel):
    name: str
    description: str | None = None


class MarkingOut(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime


class MarkingEligibilityIn(BaseModel):
    principal_type: str
    principal_id: uuid.UUID | None = None
    marking_name: str


class MarkingEligibilityOut(BaseModel):
    id: str
    principal_type: str
    principal_id: str | None
    marking_name: str
    created_at: datetime

@router.get("/metrics")
async def get_usage_metrics(
    session: SessionDep,
    user: CurrentUserDep
) -> dict:
    # 1. Fetch total credits
    total_q = await session.execute(
        select(func.sum(UsageMetric.compute_credits)).where(UsageMetric.user_id == user.id)
    )
    total_credits = float(total_q.scalar() or 0.0)

    # 2. Fetch breakdown by resource_type
    breakdown_q = await session.execute(
        select(
            UsageMetric.resource_type,
            func.sum(UsageMetric.compute_credits),
            func.count(UsageMetric.id)
        ).where(UsageMetric.user_id == user.id)
        .group_by(UsageMetric.resource_type)
    )
    breakdown = [
        {
            "resource_type": row[0],
            "total_credits": float(row[1] or 0.0),
            "count": int(row[2] or 0)
        }
        for row in breakdown_q.all()
    ]

    # 3. Fetch recent usage details
    recent_q = await session.execute(
        select(UsageMetric)
        .where(UsageMetric.user_id == user.id)
        .order_by(UsageMetric.created_at.desc())
        .limit(20)
    )
    recent = [
        {
            "id": str(r.id),
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "compute_credits": r.compute_credits,
            "execution_time_ms": r.execution_time_ms,
            "created_at": r.created_at
        }
        for r in recent_q.scalars().all()
    ]

    return {
        "total_credits": total_credits,
        "breakdown": breakdown,
        "recent_logs": recent
    }


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(session: SessionDep, _: AdminDep) -> list[GroupOut]:
    rows = (await session.execute(select(Group).order_by(Group.name))).scalars().all()
    counts = (
        await session.execute(select(GroupMember.group_id, func.count(GroupMember.user_id)).group_by(GroupMember.group_id))
    ).all()
    by_group = {group_id: int(count) for group_id, count in counts}
    return [
        GroupOut(id=str(g.id), name=g.name, description=g.description, member_count=by_group.get(g.id, 0), created_at=g.created_at)
        for g in rows
    ]


@router.post("/groups", response_model=GroupOut, status_code=201)
async def create_group(payload: GroupIn, session: SessionDep, admin: AdminDep) -> GroupOut:
    group = await get_or_create_group(session, payload.name, payload.description)
    await log_event(session, user=admin, event_type="GROUP_CREATED", resource_type="group", resource_id=str(group.id), input_summary={"name": group.name})
    await session.commit()
    return GroupOut(id=str(group.id), name=group.name, description=group.description, member_count=0, created_at=group.created_at)


@router.get("/groups/{group_id}/members")
async def list_group_members(group_id: uuid.UUID, session: SessionDep, _: AdminDep) -> dict:
    group = await session.get(Group, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "group not found")
    rows = (
        await session.execute(select(User).join(GroupMember, GroupMember.user_id == User.id).where(GroupMember.group_id == group_id).order_by(User.email))
    ).scalars().all()
    return {"group_id": str(group_id), "members": [{"id": str(u.id), "email": u.email, "name": u.name} for u in rows]}


@router.post("/groups/{group_id}/members")
async def add_member(group_id: uuid.UUID, payload: GroupMemberIn, session: SessionDep, admin: AdminDep) -> dict:
    group = await session.get(Group, group_id)
    user = await session.get(User, payload.user_id)
    if group is None or user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "group or user not found")
    await add_group_member(session, group_id, payload.user_id)
    version = await bump_permission_version(session)
    await log_event(session, user=admin, event_type="GROUP_MEMBER_ADDED", resource_type="group", resource_id=str(group_id), input_summary={"user_id": str(payload.user_id)})
    await session.commit()
    return {"ok": True, "permission_version": version}


@router.delete("/groups/{group_id}/members/{user_id}")
async def remove_member(group_id: uuid.UUID, user_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    row = (await session.execute(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id))).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
    version = await bump_permission_version(session)
    await log_event(session, user=admin, event_type="GROUP_MEMBER_REMOVED", resource_type="group", resource_id=str(group_id), input_summary={"user_id": str(user_id)})
    await session.commit()
    return {"ok": True, "permission_version": version}


@router.get("/markings", response_model=list[MarkingOut])
async def list_markings(session: SessionDep, _: AdminDep) -> list[MarkingOut]:
    rows = (await session.execute(select(Marking).order_by(Marking.name))).scalars().all()
    return [MarkingOut(id=str(m.id), name=m.name, description=m.description, created_at=m.created_at) for m in rows]


@router.post("/markings", response_model=MarkingOut, status_code=201)
async def create_marking(payload: MarkingIn, session: SessionDep, admin: AdminDep) -> MarkingOut:
    existing = (await session.execute(select(Marking).where(Marking.name == payload.name))).scalar_one_or_none()
    if existing is None:
        existing = Marking(name=payload.name, description=payload.description)
        session.add(existing)
        await session.flush()
    elif payload.description is not None:
        existing.description = payload.description
    version = await bump_permission_version(session)
    await log_event(session, user=admin, event_type="MARKING_CHANGED", resource_type="marking", resource_id=str(existing.id), input_summary={"name": existing.name, "permission_version": version})
    await session.commit()
    return MarkingOut(id=str(existing.id), name=existing.name, description=existing.description, created_at=existing.created_at)


@router.get("/markings/eligibility", response_model=list[MarkingEligibilityOut])
async def list_marking_eligibility(session: SessionDep, _: AdminDep) -> list[MarkingEligibilityOut]:
    rows = (await session.execute(select(PrincipalMarking).order_by(PrincipalMarking.principal_type, PrincipalMarking.marking_name))).scalars().all()
    return [
        MarkingEligibilityOut(
            id=str(row.id),
            principal_type=row.principal_type,
            principal_id=str(row.principal_id) if row.principal_id else None,
            marking_name=row.marking_name,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/markings/eligibility", response_model=MarkingEligibilityOut, status_code=201)
async def grant_marking_eligibility(payload: MarkingEligibilityIn, session: SessionDep, admin: AdminDep) -> MarkingEligibilityOut:
    if payload.principal_type not in {"user", "role", "group", "all_users"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "principal_type must be user|role|group|all_users")
    if payload.principal_type != "all_users" and payload.principal_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "principal_id required")
    marking = (await session.execute(select(Marking).where(Marking.name == payload.marking_name))).scalar_one_or_none()
    if marking is None:
        marking = Marking(name=payload.marking_name)
        session.add(marking)
        await session.flush()
    row = (
        await session.execute(
            select(PrincipalMarking).where(
                PrincipalMarking.principal_type == payload.principal_type,
                PrincipalMarking.principal_id == payload.principal_id,
                PrincipalMarking.marking_name == payload.marking_name,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = PrincipalMarking(principal_type=payload.principal_type, principal_id=payload.principal_id, marking_name=payload.marking_name)
        session.add(row)
        await session.flush()
    version = await bump_permission_version(session)
    await log_event(session, user=admin, event_type="MARKING_ELIGIBILITY_GRANTED", resource_type="marking", resource_id=payload.marking_name, input_summary={**payload.model_dump(mode="json"), "permission_version": version})
    await session.commit()
    return MarkingEligibilityOut(id=str(row.id), principal_type=row.principal_type, principal_id=str(row.principal_id) if row.principal_id else None, marking_name=row.marking_name, created_at=row.created_at)


@router.delete("/markings/eligibility/{eligibility_id}")
async def revoke_marking_eligibility(eligibility_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    row = await session.get(PrincipalMarking, eligibility_id)
    if row is not None:
        await session.delete(row)
    version = await bump_permission_version(session)
    await log_event(session, user=admin, event_type="MARKING_ELIGIBILITY_REVOKED", resource_type="marking", resource_id=str(eligibility_id), input_summary={"permission_version": version})
    await session.commit()
    return {"ok": True, "permission_version": version}
