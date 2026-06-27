from app.main import app


PUBLIC_ROUTES = {
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/password-reset/request"),
    ("POST", "/api/v1/auth/password-reset/confirm"),
    ("GET", "/api/v1/auth/sso/login"),
    ("GET", "/api/v1/auth/sso/callback"),
    ("GET", "/api/v1/system/health"),
}


def _dependency_names(route) -> set[str]:
    names: set[str] = set()
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return names
    stack = [dependant]
    while stack:
        current = stack.pop()
        call = getattr(current, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", str(call)))
        stack.extend(getattr(current, "dependencies", []) or [])
    return names


def test_api_routes_are_authenticated_or_explicitly_public():
    violations = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/v1"):
            continue
        for method in getattr(route, "methods", []) or []:
            if method in {"HEAD", "OPTIONS"} or (method, path) in PUBLIC_ROUTES:
                continue
            deps = _dependency_names(route)
            if "get_current_user" not in deps and "require_admin" not in deps:
                violations.append(f"{method} {path}")
    assert violations == []


def test_sensitive_routes_are_admin_only():
    admin_paths = [
        "/api/v1/admin/users",
        "/api/v1/admin/audit",
        "/api/v1/admin/permissions/grant",
        "/api/v1/governance/groups",
        "/api/v1/governance/markings",
    ]
    for path in admin_paths:
        matches = [route for route in app.routes if getattr(route, "path", "") == path]
        assert matches, path
        assert all("require_admin" in _dependency_names(route) for route in matches)
