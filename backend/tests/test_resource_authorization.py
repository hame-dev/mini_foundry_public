import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.auth.models import User
from app.permissions.enforcement import effective_resource_capabilities
from app.platform.models import Resource, ResourceACL


def _execute_result(*, rows=None, scalars=None):
    result = MagicMock()
    result.all.return_value = rows or []
    result.scalars.return_value.all.return_value = scalars or []
    return result


@pytest.mark.asyncio
async def test_parent_acl_must_be_inheritable_to_apply_to_child_resource():
    user_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    user = User(id=user_id, email="viewer@example.com", password_hash="x")
    parent = Resource(id=parent_id, resource_type="folder", object_id=uuid.uuid4(), name="Parent", owner_user_id=owner_id)
    child = Resource(
        id=child_id,
        resource_type="dataset",
        object_id=uuid.uuid4(),
        name="Child",
        owner_user_id=owner_id,
        parent_resource_id=parent_id,
    )
    parent_acl = ResourceACL(
        resource_id=parent_id,
        subject_type="user",
        subject_id=user_id,
        capabilities=["view_metadata"],
        inherit=False,
    )

    session = AsyncMock()
    session.get.return_value = parent
    session.execute.side_effect = [
        _execute_result(),  # resource markings
        _execute_result(rows=[]),  # user role names
        _execute_result(rows=[]),  # role ids
        _execute_result(rows=[]),  # group ids
        _execute_result(scalars=[parent_acl]),  # matching ACLs
    ]

    assert await effective_resource_capabilities(session, user, child) == set()


@pytest.mark.asyncio
async def test_direct_acl_applies_even_when_inherit_is_false():
    user_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    user = User(id=user_id, email="viewer@example.com", password_hash="x")
    resource = Resource(
        id=resource_id,
        resource_type="dataset",
        object_id=uuid.uuid4(),
        name="Dataset",
        owner_user_id=owner_id,
    )
    direct_acl = ResourceACL(
        resource_id=resource_id,
        subject_type="user",
        subject_id=user_id,
        capabilities=["view_metadata"],
        inherit=False,
    )

    session = AsyncMock()
    session.execute.side_effect = [
        _execute_result(),  # resource markings
        _execute_result(rows=[]),  # user role names
        _execute_result(rows=[]),  # role ids
        _execute_result(rows=[]),  # group ids
        _execute_result(scalars=[direct_acl]),  # matching ACLs
    ]

    assert await effective_resource_capabilities(session, user, resource) == {"view_metadata"}


@pytest.mark.asyncio
async def test_group_acl_applies_to_group_members():
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    resource_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    user = User(id=user_id, email="viewer@example.com", password_hash="x")
    resource = Resource(
        id=resource_id,
        resource_type="dataset",
        object_id=uuid.uuid4(),
        name="Dataset",
        owner_user_id=owner_id,
    )
    group_acl = ResourceACL(
        resource_id=resource_id,
        subject_type="group",
        subject_id=group_id,
        capabilities=["view_metadata", "view_data"],
    )

    session = AsyncMock()
    session.execute.side_effect = [
        _execute_result(),  # resource markings
        _execute_result(rows=[]),  # user role names
        _execute_result(rows=[]),  # role ids
        _execute_result(rows=[(group_id,)]),  # group ids
        _execute_result(scalars=[group_acl]),  # matching ACLs
    ]

    assert await effective_resource_capabilities(session, user, resource) == {"view_metadata", "view_data"}
