import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.auth.models import User
from app.platform.models import Project, Resource
import app.platform.router as pr
from app.platform.models import LineageEdge


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(pr, "log_event", AsyncMock())
    monkeypatch.setattr(pr, "bump_permission_version", AsyncMock(return_value=2))


def _session():
    s = AsyncMock()
    s.flush = AsyncMock()
    s.commit = AsyncMock()
    return s


def _user():
    return User(id=uuid.uuid4(), email="o@example.com")


def _project(owner_id):
    return Project(id=uuid.uuid4(), name="P", owner_id=owner_id)


@pytest.mark.asyncio
async def test_get_project_returns_counts(monkeypatch):
    user = _user()
    project = _project(user.id)
    session = _session()
    session.get.return_value = project
    monkeypatch.setattr(pr, "get_resource_for_object", AsyncMock(return_value=MagicMock(id=uuid.uuid4())))
    res = MagicMock()
    res.all.return_value = [("dataset", 3), ("pipeline", 1)]
    session.execute.return_value = res

    out = await pr.get_project(project.id, session, user)
    assert out.resource_counts == {"dataset": 3, "pipeline": 1}
    assert out.resource_total == 4


@pytest.mark.asyncio
async def test_project_cap_denied_for_non_owner(monkeypatch):
    user = _user()
    project = _project(uuid.uuid4())  # someone else
    session = _session()
    session.get.return_value = project
    monkeypatch.setattr(pr, "get_resource_for_object", AsyncMock(return_value=MagicMock(id=uuid.uuid4())))
    monkeypatch.setattr(pr, "effective_resource_capabilities", AsyncMock(return_value=set()))
    with pytest.raises(HTTPException) as exc:
        await pr._require_project_cap(session, user, project.id, "view_metadata")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_project_missing_404(monkeypatch):
    user = _user()
    session = _session()
    session.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        await pr._require_project_cap(session, user, uuid.uuid4(), "view_metadata")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_grant_access_validates_capabilities(monkeypatch):
    user = _user()
    project = _project(user.id)
    session = _session()
    session.get.return_value = project
    monkeypatch.setattr(pr, "get_resource_for_object", AsyncMock(return_value=MagicMock(id=uuid.uuid4())))
    payload = pr.ProjectAccessIn(subject_type="role", subject_id=uuid.uuid4(), capabilities=["bogus_cap"])
    with pytest.raises(HTTPException) as exc:
        await pr.grant_project_access(project.id, payload, session, user)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_grant_access_bad_subject_type(monkeypatch):
    user = _user()
    project = _project(user.id)
    session = _session()
    session.get.return_value = project
    monkeypatch.setattr(pr, "get_resource_for_object", AsyncMock(return_value=MagicMock(id=uuid.uuid4())))
    payload = pr.ProjectAccessIn(subject_type="banana", subject_id=uuid.uuid4(), capabilities=["view_metadata"])
    with pytest.raises(HTTPException) as exc:
        await pr.grant_project_access(project.id, payload, session, user)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_project_activity_fans_out(monkeypatch):
    user = _user()
    project = _project(user.id)
    session = _session()
    session.get.return_value = project
    monkeypatch.setattr(pr, "get_resource_for_object", AsyncMock(return_value=MagicMock(id=uuid.uuid4())))

    resource = Resource(id=uuid.uuid4(), resource_type="dataset", object_id=uuid.uuid4(), name="d", project_id=project.id)
    audit = MagicMock(id=uuid.uuid4(), event_type="DATASET_VIEWED", resource_type="dataset",
                      resource_id=str(resource.object_id), user_id=None)
    import datetime as dt
    audit.created_at = dt.datetime.utcnow()

    res_resources = MagicMock()
    res_resources.scalars.return_value.all.return_value = [resource]
    res_audit = MagicMock()
    res_audit.scalars.return_value.all.return_value = [audit]
    session.execute.side_effect = [res_resources, res_audit]

    out = await pr.project_activity(project.id, session, user, limit=100)
    assert out["events"][0]["event_type"] == "DATASET_VIEWED"


@pytest.mark.asyncio
async def test_resource_lineage_hides_inaccessible_nodes_and_keeps_column_metadata(monkeypatch):
    user = _user()
    root = Resource(id=uuid.uuid4(), resource_type="dataset", object_id=uuid.uuid4(), name="Visible")
    hidden = Resource(id=uuid.uuid4(), resource_type="dashboard", object_id=uuid.uuid4(), name="Hidden")
    edge = LineageEdge(
        id=uuid.uuid4(),
        source_resource_id=root.id,
        target_resource_id=hidden.id,
        edge_type="dataset_to_dashboard_widget",
        edge_metadata={"column_mappings": [{"source_column": "a", "target_column": "b", "transform": "direct"}]},
    )
    import datetime as dt
    edge.created_at = dt.datetime.utcnow()
    session = _session()
    session.get.return_value = root
    monkeypatch.setattr(pr, "effective_resource_capabilities", AsyncMock(return_value={"view_metadata"}))

    edge_rows = MagicMock()
    edge_rows.scalars.return_value.all.return_value = [edge]
    resource_rows = MagicMock()
    resource_rows.scalars.return_value.all.return_value = [root, hidden]
    session.execute.side_effect = [edge_rows, resource_rows]

    async def can_view(_session, _user, resource):
        return resource.id == root.id

    monkeypatch.setattr(pr, "_can_view_resource_node", can_view)

    out = await pr.resource_lineage(root.id, session, user, direction="downstream", depth=1, include_columns=True)

    assert len(out["nodes"]) == 1
    assert out["hidden_nodes"]["count"] == 1
    assert out["edges"][0]["source_resource_id"] == str(root.id)
    assert out["edges"][0]["target_resource_id"] is None
    assert out["edges"][0]["metadata"]["column_mappings"][0]["source_column"] == "a"


@pytest.mark.asyncio
async def test_resource_impact_returns_visible_downstream(monkeypatch):
    user = _user()
    root = Resource(id=uuid.uuid4(), resource_type="dataset", object_id=uuid.uuid4(), name="Dataset")
    app = Resource(id=uuid.uuid4(), resource_type="application", object_id=uuid.uuid4(), name="App")
    edge = LineageEdge(
        id=uuid.uuid4(),
        source_resource_id=root.id,
        target_resource_id=app.id,
        edge_type="dataset_to_application",
        edge_metadata={"column_mappings": [{"source_column": "customer_id", "target_column": "customer_id"}]},
    )
    session = _session()
    session.get.side_effect = [root, app]
    monkeypatch.setattr(pr, "_can_view_resource_node", AsyncMock(return_value=True))
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [edge]
    session.execute.return_value = rows

    out = await pr.resource_impact(root.id, session, user, depth=1, columns="customer_id")

    assert out["by_type"] == {"application": 1}
    assert out["affected"][0]["name"] == "App"
