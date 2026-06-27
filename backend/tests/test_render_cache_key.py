import uuid
from app.dashboards.cache import render_cache_key


def _kw(**overrides):
    base = {
        "user_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "dashboard_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "component_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "binding": {"type": "sql_query", "sql": "SELECT 1", "dataset_ids": []},
        "filters": {"status": "paid"},
        "permission_version": 5,
    }
    base.update(overrides)
    return base


def test_same_inputs_same_key():
    assert render_cache_key(**_kw()) == render_cache_key(**_kw())


def test_permission_version_bumps_key():
    assert render_cache_key(**_kw()) != render_cache_key(**_kw(permission_version=6))


def test_different_filter_value_changes_key():
    a = render_cache_key(**_kw(filters={"status": "paid"}))
    b = render_cache_key(**_kw(filters={"status": "pending"}))
    assert a != b


def test_different_user_changes_key():
    a = render_cache_key(**_kw())
    b = render_cache_key(**_kw(user_id=uuid.UUID("99999999-9999-9999-9999-999999999999")))
    assert a != b


def test_dataset_version_context_changes_key():
    a = render_cache_key(
        **_kw(cache_context={"dataset_versions": [{"dataset_id": "d1", "dataset_version_id": "v1"}], "engine": "postgres"})
    )
    b = render_cache_key(
        **_kw(cache_context={"dataset_versions": [{"dataset_id": "d1", "dataset_version_id": "v2"}], "engine": "postgres"})
    )
    assert a != b


def test_engine_context_changes_key():
    a = render_cache_key(**_kw(cache_context={"dataset_versions": [], "engine": "postgres"}))
    b = render_cache_key(**_kw(cache_context={"dataset_versions": [], "engine": "trino"}))
    assert a != b


def test_key_starts_with_component_namespace():
    key = render_cache_key(**_kw())
    assert key.startswith("dashboard:component:33333333-3333-3333-3333-333333333333:result:")
