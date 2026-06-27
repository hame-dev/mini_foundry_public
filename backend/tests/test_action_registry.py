import pytest
from unittest.mock import AsyncMock, MagicMock
import uuid

from fastapi import HTTPException
from app.actions import service as action_service
from app.actions import router as actions_router
from app.actions.execution import execute_action_run
from app.actions.registry import (
    WORKFLOWS,
    get_workflow,
    list_workflows,
    load_user_workflows,
    validate_params,
    workflow,
)
from app.auth.models import User
from app.ontology.models import ActionRun, OntologyAction
from app.platform import router as platform_router
from app.platform.models import ApprovalRequest


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Scalars:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _ScalarsResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return _Scalars(self.values)


def test_register_and_get():
    load_user_workflows()
    assert "ping" in WORKFLOWS
    assert get_workflow("ping")["sync"] is True


def test_unknown_workflow_raises():
    with pytest.raises(KeyError):
        get_workflow("not_a_real_workflow_xyz")


def test_decorator_registers_async():
    @workflow("__test_async", sync=False)
    def fn(session, user, params):
        return {}
    try:
        assert WORKFLOWS["__test_async"]["sync"] is False
    finally:
        WORKFLOWS.pop("__test_async", None)


def test_list_workflows_returns_sorted_dicts():
    entries = list_workflows()
    assert all("name" in e and "sync" in e for e in entries)
    names = [e["name"] for e in entries]
    assert names == sorted(names)


# --- validate_params -----------------------------------------------------


def test_validate_params_no_schema_ok():
    validate_params(None, {})
    validate_params({}, {"a": 1})


def test_validate_required_missing():
    with pytest.raises(ValueError, match="customer_id"):
        validate_params({"required": ["customer_id"]}, {})


def test_validate_type_string():
    with pytest.raises(ValueError, match="expected string"):
        validate_params({"properties": {"name": {"type": "string"}}}, {"name": 5})


def test_validate_type_uuid_bad():
    with pytest.raises(ValueError, match="invalid uuid"):
        validate_params({"properties": {"id": {"type": "uuid"}}}, {"id": "not-a-uuid"})


def test_validate_type_uuid_ok():
    validate_params(
        {"properties": {"id": {"type": "uuid"}}},
        {"id": "00000000-0000-0000-0000-000000000001"},
    )


def test_validate_optional_omitted_ok():
    validate_params({"properties": {"flag": {"type": "boolean"}}}, {})


def test_action_preconditions_support_nested_rules():
    failures = action_service.evaluate_preconditions(
        {
            "all": [
                {"param": "status", "equals": "open"},
                {"any": [{"param": "priority", "in": ["high", "urgent"]}, {"param": "override", "equals": True}]},
            ]
        },
        {"status": "open", "priority": "high"},
    )
    assert failures == []


def test_action_preconditions_report_failures():
    failures = action_service.evaluate_preconditions(
        {"param": "status", "equals": "open"},
        {"status": "closed"},
    )
    assert failures and "status" in failures[0]


@pytest.mark.asyncio
async def test_action_permission_uses_central_resource_capability(monkeypatch):
    user = User(id=uuid.uuid4(), email="runner@example.com", password_hash="x")
    action = OntologyAction(
        id=uuid.uuid4(),
        name="UpdateOrder",
        workflow_key="ping",
        requires_capability="can_run_action",
    )
    session = AsyncMock()
    monkeypatch.setattr(action_service, "effective_capabilities_for_object", AsyncMock(return_value={"run"}))

    assert await action_service.user_can_run_action(session, user, action) is True
    action_service.effective_capabilities_for_object.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_action_run_marks_missing_workflow_failed():
    user = User(id=uuid.uuid4(), email="runner@example.com", password_hash="x")
    action = OntologyAction(
        id=uuid.uuid4(),
        name="MissingWorkflow",
        workflow_key="__missing_workflow__",
        enabled=True,
    )
    action_run = ActionRun(id=uuid.uuid4(), action_id=action.id, user_id=user.id, status="running", input={})
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_ScalarResult(None))

    with pytest.raises(HTTPException):
        await execute_action_run(session, user=user, action=action, action_run=action_run, params={})

    assert action_run.status == "failed"
    assert "workflow not loaded" in action_run.error
    assert action_run.finished_at is not None


@pytest.mark.asyncio
async def test_trigger_commits_controlled_action_failure(monkeypatch):
    user = User(id=uuid.uuid4(), email="runner@example.com", password_hash="x")
    action = OntologyAction(
        id=uuid.uuid4(),
        name="FailingAction",
        workflow_key="ping",
        enabled=True,
    )
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[_ScalarResult(action), _ScalarResult(None)])
    session.add = MagicMock()
    monkeypatch.setattr(actions_router.service, "user_can_run_action", AsyncMock(return_value=True))
    monkeypatch.setattr(
        actions_router,
        "execute_action_run",
        AsyncMock(side_effect=HTTPException(status_code=500, detail="controlled failure")),
    )

    with pytest.raises(HTTPException):
        await actions_router.trigger(actions_router.TriggerIn(action_name="FailingAction"), session, user)

    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_public_action_list_filters_object_type_and_exposes_permission(monkeypatch):
    user = User(id=uuid.uuid4(), email="runner@example.com", password_hash="x")
    matching = OntologyAction(
        id=uuid.uuid4(),
        name="UpdateOrder",
        workflow_key="ping",
        object_type="Order",
        requires_capability="can_run_action",
        enabled=True,
    )
    global_action = OntologyAction(
        id=uuid.uuid4(),
        name="GlobalRefresh",
        workflow_key="ping",
        object_type=None,
        requires_capability="can_run_action",
        enabled=True,
    )
    other = OntologyAction(
        id=uuid.uuid4(),
        name="UpdateInvoice",
        workflow_key="ping",
        object_type="Invoice",
        requires_capability="can_run_action",
        enabled=True,
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_ScalarsResult([matching, global_action, other]))
    monkeypatch.setattr(actions_router.service, "user_can_run_action", AsyncMock(side_effect=[True, False]))

    rows = await actions_router.list_runnable_actions(session, user, object_type="Order")

    assert [row.name for row in rows] == ["UpdateOrder", "GlobalRefresh"]
    assert rows[0].can_run is True
    assert rows[1].can_run is False
    assert "Requires" in (rows[1].permission_explanation or "")


@pytest.mark.asyncio
async def test_action_approval_rejection_closes_pending_run(monkeypatch):
    approval = ApprovalRequest(id=uuid.uuid4(), approval_type="action", status="pending")
    action_run = ActionRun(
        id=uuid.uuid4(),
        action_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        status="pending_approval",
        input={"status": "open"},
    )
    decider = User(id=uuid.uuid4(), email="owner@example.com", password_hash="x")
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_ScalarResult(action_run))
    monkeypatch.setattr(platform_router, "log_event", AsyncMock())

    result = await platform_router._apply_action_approval_decision(
        session,
        approval=approval,
        approved=False,
        decider=decider,
        note="needs review",
    )

    assert result["action_run_status"] == "rejected"
    assert action_run.status == "rejected"
    assert action_run.error == "needs review"
    assert action_run.finished_at is not None


@pytest.mark.asyncio
async def test_action_approval_executes_as_original_requester(monkeypatch):
    action_id = uuid.uuid4()
    requester_id = uuid.uuid4()
    approval = ApprovalRequest(id=uuid.uuid4(), approval_type="action", status="pending")
    action_run = ActionRun(
        id=uuid.uuid4(),
        action_id=action_id,
        user_id=requester_id,
        status="pending_approval",
        input={"status": "open"},
    )
    action = OntologyAction(
        id=action_id,
        name="ApproveOrder",
        workflow_key="ping",
        requires_capability="can_run_action",
        enabled=True,
        preconditions={"param": "status", "equals": "open"},
    )
    requester = User(id=requester_id, email="requester@example.com", password_hash="x")
    decider = User(id=uuid.uuid4(), email="owner@example.com", password_hash="x")
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_ScalarResult(action_run))

    async def fake_get(model, item_id):
        if model is OntologyAction and item_id == action_id:
            return action
        if model is User and item_id == requester_id:
            return requester
        return None

    async def fake_execute_action_run(session, *, user, action, action_run, params):
        assert user is requester
        action_run.status = "succeeded"
        action_run.output = {"ok": True}
        return {"status": "succeeded", "action_run_id": str(action_run.id), "output": {"ok": True}}

    session.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr(platform_router.action_service, "user_can_run_action", AsyncMock(return_value=True))
    monkeypatch.setattr(platform_router, "execute_action_run", AsyncMock(side_effect=fake_execute_action_run))
    monkeypatch.setattr(platform_router, "log_event", AsyncMock())

    result = await platform_router._apply_action_approval_decision(
        session,
        approval=approval,
        approved=True,
        decider=decider,
        note=None,
    )

    assert result["action_run_status"] == "succeeded"
    assert action_run.status == "succeeded"
    assert action_run.output == {"ok": True}
    platform_router.execute_action_run.assert_awaited_once()
