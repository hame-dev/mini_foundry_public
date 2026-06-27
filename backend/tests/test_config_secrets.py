"""Production secret-hardening guard (Phase 0).

``production_hardening_issues`` is enforced at startup in app.main.lifespan:
in a ``production`` environment with ``require_production_hardening`` the app
refuses to boot while any dev default remains.
"""
from app.config import Settings, production_hardening_issues


def test_development_tolerates_defaults():
    s = Settings(environment="development")
    assert production_hardening_issues(s) == []


def test_production_flags_default_secrets():
    s = Settings(
        environment="production",
        jwt_secret="change-me-in-production",
        encryption_key="dev-secret-key-change-me-in-prod-32chars",
        admin_password="admin",
    )
    issues = production_hardening_issues(s)
    assert any("jwt_secret" in i for i in issues)
    assert any("encryption_key" in i for i in issues)
    assert any("admin_password" in i for i in issues)


def test_production_passes_with_strong_secrets():
    s = Settings(
        environment="production",
        jwt_secret="x" * 48,
        encryption_key="y" * 48,
        admin_password="a-strong-admin-password",
    )
    issues = production_hardening_issues(s)
    assert not any("jwt_secret" in i for i in issues)
    assert not any("encryption_key" in i for i in issues)
    assert not any("admin_password" in i for i in issues)


def test_sandbox_isolation_settings_exist():
    s = Settings(environment="development")
    # New Phase 0 knobs for isolating the sandbox from the host Docker daemon.
    assert hasattr(s, "sandbox_docker_host")
    assert hasattr(s, "sandbox_runtime")
