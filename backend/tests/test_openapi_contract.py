from app.main import app


def test_openapi_contains_platform_contract_surfaces():
    schema = app.openapi()
    paths = schema["paths"]
    required_paths = [
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/password-reset/request",
        "/api/v1/governance/groups",
        "/api/v1/governance/markings/eligibility",
        "/api/v1/platform/resources",
        "/api/v1/platform/resources/{resource_id}/exports",
        "/api/v1/platform/branches/{branch_id}/compare",
        "/api/v1/dashboards/{dashboard_id}/render",
        "/api/v1/models/{model_id}/versions/{version_id}/promote",
        "/api/v1/applications/{application_id}/publish",
    ]
    missing = [path for path in required_paths if path not in paths]
    assert missing == []


def test_openapi_has_no_legacy_localstorage_auth_contract():
    schema = app.openapi()
    auth_login = schema["paths"]["/api/v1/auth/login"]["post"]
    response_schema = auth_login["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("/TokenOut")
    token_out = schema["components"]["schemas"]["TokenOut"]["properties"]
    assert token_out["token_type"].get("default") == "cookie"
