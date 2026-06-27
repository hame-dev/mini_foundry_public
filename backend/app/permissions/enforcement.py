"""Permission enforcement.

ResourceACL is the single source of truth for runtime authorization. Use
``effective_resource_capabilities`` / ``effective_capabilities_for_object`` /
``require_object_capability`` (and their ``_sync`` variants) for all data-access
checks; these also enforce security markings and parent/project inheritance.

The legacy per-dataset ``DatasetPermission`` model and its enforcement helpers
were removed in Phase 1 (migration 0034 drops the ``dataset_permissions`` table);
all grants now live in ``resource_acl``.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import GroupMember, PrincipalMarking, Role, User, UserRole
from app.auth.service import effective_marking_names, get_user_group_ids, get_user_roles
from app.audit.logger import log_event
from app.permissions.models import PermissionVersion
from app.platform.models import Marking, Resource, ResourceACL, ResourceMarking
from app.platform.service import CANONICAL_CAPABILITIES, get_resource_for_object


async def _user_role_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    result = await session.execute(select(UserRole.role_id).where(UserRole.user_id == user_id))
    return [row[0] for row in result.all()]


def _dataset_cap_to_canonical(capability: str) -> str:
    return {
        "can_view_metadata": "view_metadata",
        "can_view_data": "view_data",
        "can_use_in_sql": "use_in_sql",
        "can_use_in_python": "use_in_python",
        "can_use_with_ai": "use_with_ai",
        "can_export": "export",
        "can_edit": "edit",
        "can_manage": "manage",
        "can_run_action": "run",
        "can_run": "run",
        "can_grant": "grant",
        "can_publish": "publish",
        "can_writeback": "writeback",
    }.get(capability, capability.removeprefix("can_"))


def _canonical_to_dataset_attr(capability: str) -> str:
    return {
        "view_metadata": "can_view_metadata",
        "view_data": "can_view_data",
        "use_in_sql": "can_use_in_sql",
        "use_in_python": "can_use_in_python",
        "use_with_ai": "can_use_with_ai",
        "export": "can_export",
        "edit": "can_edit",
        "manage": "can_manage",
        "can_run_action": "can_run",
        "run": "can_run",
        "grant": "can_grant",
        "publish": "can_publish",
        "writeback": "can_writeback",
    }.get(capability, capability)


async def _subject_ids(session: AsyncSession, user_id: uuid.UUID) -> list[tuple[str, uuid.UUID | None]]:
    role_ids = await _user_role_ids(session, user_id)
    group_ids = await get_user_group_ids(session, user_id)
    return [("user", user_id), *[("role", rid) for rid in role_ids], *[("group", gid) for gid in group_ids], ("all_users", None)]


async def effective_resource_capabilities(session: AsyncSession, user: User, resource: Resource) -> set[str]:
    """Central resource authorization, including inherited parent/project ACLs."""
    if not await resource_markings_allowed(session, user, resource):
        return set()

    roles = await get_user_roles(session, user.id)
    if "admin" in roles:
        return set(CANONICAL_CAPABILITIES)

    if resource.owner_user_id == user.id:
        return set(CANONICAL_CAPABILITIES)

    subjects = await _subject_ids(session, user.id)
    resource_ids: list[uuid.UUID] = []
    direct_resource_id = resource.id
    current: Resource | None = resource
    while current is not None:
        resource_ids.append(current.id)
        if current.parent_resource_id is None:
            break
        current = await session.get(Resource, current.parent_resource_id)

    if resource.project_id:
        project_resource = (
            await session.execute(
                select(Resource).where(Resource.resource_type == "project", Resource.object_id == resource.project_id)
            )
        ).scalar_one_or_none()
        if project_resource:
            resource_ids.append(project_resource.id)

    rows = (
        await session.execute(
            select(ResourceACL).where(
                ResourceACL.resource_id.in_(resource_ids),
                ResourceACL.subject_type.in_([s[0] for s in subjects]),
            )
        )
    ).scalars().all()
    subject_set = set(subjects)
    caps: set[str] = set()
    for row in rows:
        if (row.subject_type, row.subject_id) in subject_set:
            if row.resource_id != direct_resource_id and not row.inherit:
                continue
            caps.update(row.capabilities or [])
    return caps


async def resource_markings_allowed(session: AsyncSession, user: User, resource: Resource) -> bool:
    resource_ids: list[uuid.UUID] = []
    current: Resource | None = resource
    while current is not None:
        resource_ids.append(current.id)
        if current.parent_resource_id is None:
            break
        current = await session.get(Resource, current.parent_resource_id)

    if resource.project_id:
        project_resource = (
            await session.execute(
                select(Resource).where(Resource.resource_type == "project", Resource.object_id == resource.project_id)
            )
        ).scalar_one_or_none()
        if project_resource:
            resource_ids.append(project_resource.id)

    marking_rows = (
        await session.execute(
            select(Marking.name)
            .join(ResourceMarking, ResourceMarking.marking_id == Marking.id)
            .where(ResourceMarking.resource_id.in_(resource_ids))
        )
    ).all()
    required_markings = {row[0] for row in marking_rows}
    return not required_markings or required_markings.issubset(await effective_marking_names(session, user))


async def effective_capabilities_for_object(
    session: AsyncSession,
    user: User,
    resource_type: str,
    object_id: uuid.UUID,
) -> set[str]:
    resource = await get_resource_for_object(session, resource_type, object_id)
    if resource is not None:
        return await effective_resource_capabilities(session, user, resource)
    return set()


async def require_object_capability(
    session: AsyncSession,
    user: User,
    resource_type: str,
    object_id: uuid.UUID,
    capability: str,
) -> None:
    canonical = _dataset_cap_to_canonical(capability)
    caps = await effective_capabilities_for_object(session, user, resource_type, object_id)
    if canonical not in caps and "manage" not in caps:
        resource = await get_resource_for_object(session, resource_type, object_id)
        await log_event(
            session,
            user=user,
            event_type="AUTHORIZATION_DENIED",
            resource_type=resource_type,
            resource_id=str(object_id),
            input_summary={"capability": canonical, "resource_id": str(resource.id) if resource else None},
        )
        raise PermissionDenied(f"missing capability: {canonical}")


async def explain_resource_permission(session: AsyncSession, user: User, resource_id: uuid.UUID, capability: str) -> dict:
    resource = await session.get(Resource, resource_id)
    if resource is None:
        return {"allowed": False, "reason": "resource not found", "capability": capability}
    caps = await effective_resource_capabilities(session, user, resource)
    canonical = _dataset_cap_to_canonical(capability)
    allowed = canonical in caps or "manage" in caps
    return {
        "allowed": allowed,
        "capability": canonical,
        "resource_id": str(resource_id),
        "resource_type": resource.resource_type,
        "reason": "owner_or_acl" if allowed else "missing_capability_or_marking",
        "effective_capabilities": sorted(caps),
    }


async def get_permission_version(session: AsyncSession) -> int:
    row = await session.get(PermissionVersion, "global")
    return int(row.version) if row else 1


async def get_permission_version_scope(session: AsyncSession, scope: str) -> int:
    row = await session.get(PermissionVersion, scope)
    return int(row.version) if row else 1


async def bump_permission_version(session: AsyncSession, scope: str = "global") -> int:
    row = await session.get(PermissionVersion, scope)
    if row is None:
        row = PermissionVersion(scope=scope, version=1)
        session.add(row)
    else:
        row.version = int(row.version) + 1
    await session.flush()
    return int(row.version)


async def policy_cache_versions(session: AsyncSession, dataset_ids: list[uuid.UUID]) -> tuple[int, int]:
    if not dataset_ids:
        version = await get_permission_version(session)
        return version, version
    row_versions = []
    mask_versions = []
    for dataset_id in dataset_ids:
        row_versions.append(await get_permission_version_scope(session, f"row_policy:{dataset_id}"))
        mask_versions.append(await get_permission_version_scope(session, f"column_mask:{dataset_id}"))
    return max(row_versions or [1]), max(mask_versions or [1])


class PermissionDenied(Exception):
    pass


def _subject_ids_sync(session, user_id: uuid.UUID) -> list[tuple[str, uuid.UUID | None]]:
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
    return [("user", user_id), *[("role", rid) for rid in role_ids], *[("group", gid) for gid in group_ids], ("all_users", None)]


def _user_role_names_sync(session, user_id: uuid.UUID) -> list[str]:
    return [
        row[0]
        for row in session.query(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .filter(UserRole.user_id == user_id)
        .all()
    ]


def _effective_marking_names_sync(session, user: User) -> set[str]:
    subjects = _subject_ids_sync(session, user.id)
    subject_set = set(subjects)
    rows = (
        session.query(PrincipalMarking)
        .filter(PrincipalMarking.principal_type.in_([subject[0] for subject in subjects]))
        .all()
    )
    names = set(user.security_markings or [])
    for row in rows:
        if (row.principal_type, row.principal_id) in subject_set:
            names.add(row.marking_name)
    return names


def _resource_markings_allowed_sync(session, user: User, resource: Resource) -> bool:
    resource_ids: list[uuid.UUID] = []
    current: Resource | None = resource
    while current is not None:
        resource_ids.append(current.id)
        if current.parent_resource_id is None:
            break
        current = session.get(Resource, current.parent_resource_id)

    if resource.project_id:
        project_resource = (
            session.query(Resource)
            .filter(Resource.resource_type == "project", Resource.object_id == resource.project_id)
            .first()
        )
        if project_resource:
            resource_ids.append(project_resource.id)

    marking_rows = (
        session.query(Marking.name)
        .join(ResourceMarking, ResourceMarking.marking_id == Marking.id)
        .filter(ResourceMarking.resource_id.in_(resource_ids))
        .all()
    )
    required_markings = {row[0] for row in marking_rows}
    return not required_markings or required_markings.issubset(_effective_marking_names_sync(session, user))


def effective_resource_capabilities_sync(session, user_id: uuid.UUID, resource: Resource) -> set[str]:
    user = session.get(User, user_id)
    if user is None or not _resource_markings_allowed_sync(session, user, resource):
        return set()
    if "admin" in _user_role_names_sync(session, user_id):
        return set(CANONICAL_CAPABILITIES)
    if resource.owner_user_id == user_id:
        return set(CANONICAL_CAPABILITIES)

    subjects = _subject_ids_sync(session, user_id)
    subject_set = set(subjects)
    resource_ids: list[uuid.UUID] = []
    direct_resource_id = resource.id
    current: Resource | None = resource
    while current is not None:
        resource_ids.append(current.id)
        if current.parent_resource_id is None:
            break
        current = session.get(Resource, current.parent_resource_id)

    if resource.project_id:
        project_resource = (
            session.query(Resource)
            .filter(Resource.resource_type == "project", Resource.object_id == resource.project_id)
            .first()
        )
        if project_resource:
            resource_ids.append(project_resource.id)

    rows = (
        session.query(ResourceACL)
        .filter(
            ResourceACL.resource_id.in_(resource_ids),
            ResourceACL.subject_type.in_([subject[0] for subject in subjects]),
        )
        .all()
    )
    caps: set[str] = set()
    for row in rows:
        if (row.subject_type, row.subject_id) in subject_set:
            if row.resource_id != direct_resource_id and not row.inherit:
                continue
            caps.update(row.capabilities or [])
    return caps


def require_object_capability_sync(
    session,
    user_id: uuid.UUID,
    resource_type: str,
    object_id: uuid.UUID,
    capability: str,
) -> None:
    canonical = _dataset_cap_to_canonical(capability)
    resource = (
        session.query(Resource)
        .filter(Resource.resource_type == resource_type, Resource.object_id == object_id)
        .first()
    )
    if resource is None:
        raise PermissionDenied(f"missing capability: {canonical}")
    caps = effective_resource_capabilities_sync(session, user_id, resource)
    if canonical not in caps and "manage" not in caps:
        raise PermissionDenied(f"missing capability: {canonical}")
