import uuid

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from app.applications.models import Application
from app.auth.models import User
from app.platform.models import Resource
import app.applications.router as appsr


def _session():
    s = AsyncMock()
    s.flush = AsyncMock()
    s.commit = AsyncMock()
    return s


def _app(owner_id):
    return Application(id=uuid.uuid4(), name="A", owner_id=owner_id, config={})


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(appsr, "log_event", AsyncMock())


@pytest.mark.asyncio
async def test_publish_snapshots_pages_and_versions(monkeypatch):
    user = User(id=uuid.uuid4(), email="o@example.com")
    app = _app(user.id)
    session = _session()
    session.get.return_value = app

    monkeypatch.setattr(appsr, "effective_capabilities_for_object", AsyncMock(return_value=set()))
    monkeypatch.setattr(appsr, "_page_snapshot", AsyncMock(return_value=[{"title": "P1", "object_type": "Customer", "config": {}}]))
    resource = MagicMock(id=uuid.uuid4())
    monkeypatch.setattr(appsr, "get_resource_for_object", AsyncMock(return_value=resource))
    reg = AsyncMock()
    monkeypatch.setattr(appsr, "register_resource_version", reg)
    monkeypatch.setattr(appsr, "_record_app_lineage", AsyncMock())
    # _app_out reads pages from DB; stub it
    monkeypatch.setattr(appsr, "_app_out", AsyncMock(return_value=MagicMock()))

    await appsr.publish_application(app.id, session, user)

    assert app.status == "published"
    assert app.published_config["pages"] == [{"title": "P1", "object_type": "Customer", "config": {}}]
    assert reg.await_count == 1
    # manifest carries the publish snapshot
    _, kwargs = reg.call_args
    assert kwargs["manifest"]["kind"] == "application_publish"


@pytest.mark.asyncio
async def test_lineage_dedupes_on_republish(monkeypatch):
    user = User(id=uuid.uuid4(), email="o@example.com")
    app = _app(user.id)
    session = _session()
    app_resource = MagicMock(id=uuid.uuid4())
    monkeypatch.setattr(appsr, "get_resource_for_object", AsyncMock(side_effect=lambda s, t, oid: app_resource if t == "application" else MagicMock(id=uuid.uuid4(), dataset_id=uuid.uuid4())))

    ot_res_id = uuid.uuid4()
    # existing edge already present for (ot_res_id, object_type_to_application)
    existing = MagicMock()
    existing.all.return_value = [(ot_res_id, "object_type_to_application")]
    session.execute.return_value = existing

    rec = AsyncMock()
    monkeypatch.setattr(appsr, "record_lineage", rec)

    # object type resolves to a resource whose id equals the already-recorded edge source
    obj = MagicMock(id=uuid.uuid4(), dataset_id=uuid.uuid4())

    async def fake_get(s, t, oid):
        if t == "application":
            return app_resource
        if t == "ontology_object_type":
            return MagicMock(id=ot_res_id)
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(appsr, "get_resource_for_object", fake_get)

    # session.execute used for both the existing-edges query and the OntologyObject lookup;
    # make scalar_one_or_none return our obj
    existing.scalar_one_or_none.return_value = obj

    await appsr._record_app_lineage(session, app, [{"title": "P", "object_type": "Customer", "config": {}}])

    # the object_type edge was already present -> not re-recorded
    recorded_edges = [c.kwargs.get("edge_type") for c in rec.call_args_list]
    assert "object_type_to_application" not in recorded_edges


@pytest.mark.asyncio
async def test_get_published_404_when_not_published(monkeypatch):
    user = User(id=uuid.uuid4(), email="o@example.com")
    app = _app(user.id)
    app.published_config = None
    session = _session()
    session.get.return_value = app
    monkeypatch.setattr(appsr, "effective_capabilities_for_object", AsyncMock(return_value=set()))
    with pytest.raises(HTTPException) as exc:
        await appsr.get_published_application(app.id, session, user)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_versions_requires_cap(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    app = _app(uuid.uuid4())  # not owner
    session = _session()
    session.get.return_value = app
    monkeypatch.setattr(appsr, "effective_capabilities_for_object", AsyncMock(return_value=set()))
    with pytest.raises(HTTPException) as exc:
        await appsr.list_app_versions(app.id, session, user)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_published_runtime_uses_snapshot_not_draft(monkeypatch):
    user = User(id=uuid.uuid4(), email="o@example.com")
    app = _app(user.id)
    app.name = "Draft name"
    app.config = {"draft": True}
    app.published_config = {
        "name": "Published name",
        "config": {"draft": False},
        "pages": [{"id": str(uuid.uuid4()), "title": "Published page", "page_type": "object_table", "object_type": None, "config": {"widgets": []}, "position": 0}],
        "published_version": 7,
    }
    session = _session()
    session.get.return_value = app
    monkeypatch.setattr(appsr, "effective_capabilities_for_object", AsyncMock(return_value=set()))
    monkeypatch.setattr(appsr, "get_user_roles", AsyncMock(return_value=[]))
    monkeypatch.setattr(appsr, "_app_latest_published_version", AsyncMock(return_value=7))

    out = await appsr.get_published_application(app.id, session, user)

    assert out.name == "Published name"
    assert out.config == {"draft": False}
    assert out.pages[0]["title"] == "Published page"
    assert out.published_version == 7


@pytest.mark.asyncio
async def test_runtime_hides_role_and_capability_denied_widgets(monkeypatch):
    user = User(id=uuid.uuid4(), email="o@example.com")
    app = _app(user.id)
    dataset_resource = Resource(id=uuid.uuid4(), resource_type="dataset", object_id=uuid.uuid4(), name="Secret")
    session = _session()
    monkeypatch.setattr(appsr, "get_user_roles", AsyncMock(return_value=[]))
    monkeypatch.setattr(appsr, "_resource_by_object", AsyncMock(return_value=dataset_resource))
    monkeypatch.setattr(appsr, "effective_resource_capabilities", AsyncMock(return_value=set()))
    monkeypatch.setattr(appsr, "_app_latest_published_version", AsyncMock(return_value=1))

    snapshot = {
        "name": "Runtime",
        "config": {},
        "pages": [
            {"title": "Admin", "page_type": "object_table", "object_type": None, "role_visibility": ["admin"], "config": {"widgets": []}},
            {"title": "Main", "page_type": "object_table", "object_type": None, "config": {"widgets": [{"id": "w1", "dataset_id": str(dataset_resource.object_id)}]}},
        ],
    }

    out = await appsr._runtime_snapshot(session, user, app, snapshot, mode="published")

    assert [p["title"] for p in out.pages] == ["Main"]
    assert out.pages[0]["config"]["widgets"] == []
    assert {n["reason"] for n in out.notices} == {"role_visibility", "missing_dataset_capability"}


@pytest.mark.asyncio
async def test_preview_requires_edit_cap(monkeypatch):
    user = User(id=uuid.uuid4(), email="v@example.com")
    app = _app(uuid.uuid4())
    session = _session()
    session.get.return_value = app
    monkeypatch.setattr(appsr, "effective_capabilities_for_object", AsyncMock(return_value={"view_metadata"}))
    with pytest.raises(HTTPException) as exc:
        await appsr.preview_application(app.id, session, user)
    assert exc.value.status_code == 404
