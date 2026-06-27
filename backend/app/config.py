from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://mini:mini@localhost:5432/mini_foundry"
    sync_database_url: str = "postgresql://mini:mini@localhost:5432/mini_foundry"
    readonly_sync_database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me-in-production"
    jwt_expires_hours: int = 8
    jwt_algorithm: str = "HS256"
    environment: str = "development"
    allow_bearer_auth: bool = False
    # When False (default/production), user code is only ever executed inside the
    # locked-down Docker sandbox via worker jobs — never in a backend process.
    # Set True only for local dev / unit tests where Docker is unavailable.
    allow_inprocess_code_exec: bool = False
    require_production_hardening: bool = True
    backup_restore_verified: bool = False
    metrics_alerting_configured: bool = False
    rootless_sandbox_host: bool = False
    # Isolate the sandbox from the host Docker daemon. When set, the worker talks
    # to a dedicated/rootless/remote daemon (DOCKER_HOST) instead of mounting the
    # privileged host socket, so a worker compromise cannot become host root.
    sandbox_docker_host: str = ""  # e.g. tcp://docker-rootless:2375 or unix:///run/user/1000/docker.sock
    # Optional hardened OCI runtime for sandbox containers (e.g. "runsc" for
    # gVisor, "kata-runtime" for Kata). Empty uses the daemon default.
    sandbox_runtime: str = ""
    sandbox_image: str = "mini-foundry-sandbox:0.5"
    sandbox_allowed_packages: str = "pandas,numpy,matplotlib,scikit-learn,scipy,pyarrow,duckdb,pytest"
    sandbox_disk_quota_mb: int = 256
    sandbox_artifact_retention_days: int = 30
    session_cookie_name: str = "mf_session"
    csrf_cookie_name: str = "mf_csrf"
    session_expires_hours: int = 8
    login_lockout_attempts: int = 5
    login_lockout_window_minutes: int = 15
    login_lockout_minutes: int = 15
    password_reset_expires_minutes: int = 30
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_group_claim: str = "groups"
    oidc_role_claim: str = "roles"
    oidc_default_roles: str = "viewer"
    oidc_require_email_verified: bool = False
    saml_metadata_url: str = ""
    saml_entity_id: str = ""
    saml_acs_url: str = ""
    saml_default_roles: str = "viewer"
    ldap_url: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_user_base_dn: str = ""
    ldap_group_base_dn: str = ""
    ldap_group_member_attr: str = "member"
    ldap_sync_enabled: bool = False
    secret_manager_provider: str = "local"  # local | vault | sops
    vault_addr: str = ""
    vault_token: str = ""
    vault_kv_mount: str = "secret"
    sops_file_path: str = ""
    encryption_key: str = "dev-secret-key-change-me-in-prod-32chars"

    admin_email: str = "admin@mini.local"
    admin_password: str = "admin"

    seed_demo_data: bool = True

    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "qwen3.5:4b"

    gemini_api_key: str = ""
    gemini_default_model: str = "gemini-1.5-pro"

    custom_ai_base_url: str = ""
    custom_ai_key: str = ""
    custom_ai_default_model: str = ""

    frontend_origin: str = "http://localhost:3000"
    backend_public_origin: str = "http://localhost:8000"
    sql_query_timeout_seconds: int = 30
    sql_row_limit: int = 1000
    sql_max_planned_cost: float = 100000.0
    sql_daily_user_credit_quota: float = 100.0
    sql_daily_project_credit_quota: float = 1000.0
    max_upload_bytes: int = 100 * 1024 * 1024
    max_upload_columns: int = 1000
    audit_retention_days: int = 365
    custom_regex_classifiers: str = ""  # JSON list: [{"label":"pii.ssn","pattern":"...","marking":"PII"}]

    # v0.8 lakehouse
    storage_backend: str = "s3"  # s3 | local
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "mini-foundry"
    local_storage_path: str = "./data_lake"
    duckdb_memory_limit: str = "1GB"
    duckdb_query_timeout_seconds: int = 30

    trino_host: str = ""
    trino_port: int = 8080
    trino_user: str = "mini-foundry"
    trino_catalog: str = "hive"
    trino_schema: str = "default"

    spark_runner_type: str = "trino"
    spark_connect_url: str = "sc://spark:15002"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def production_hardening_issues(settings: Settings | None = None) -> list[str]:
    s = settings or get_settings()
    if s.environment == "development":
        return []
    issues: list[str] = []
    if s.allow_bearer_auth:
        issues.append("allow_bearer_auth must be false outside development")
    if s.jwt_secret == "change-me-in-production" or len(s.jwt_secret) < 32:
        issues.append("jwt_secret must be replaced with a strong secret")
    if s.encryption_key == "dev-secret-key-change-me-in-prod-32chars" or len(s.encryption_key) < 32:
        issues.append("encryption_key must be replaced with a strong key")
    if s.admin_password == "admin":
        issues.append("admin_password must be replaced")
    if s.storage_backend == "s3" and {s.s3_access_key, s.s3_secret_key} <= {"minioadmin"}:
        issues.append("default object storage credentials must be replaced")
    if s.frontend_origin.startswith("http://"):
        issues.append("frontend_origin must use https outside development")
    if s.backend_public_origin.startswith("http://"):
        issues.append("backend_public_origin must use https outside development")
    if not s.readonly_sync_database_url:
        issues.append("readonly_sync_database_url must point at a least-privilege query role")
    if not s.backup_restore_verified:
        issues.append("backup_restore_verified must be true after a restore drill")
    if not s.metrics_alerting_configured:
        issues.append("metrics_alerting_configured must be true after alerts are configured")
    if not s.rootless_sandbox_host:
        issues.append("rootless_sandbox_host must be true for the sandbox worker host")
    if "@sha256:" not in s.sandbox_image:
        issues.append("sandbox_image must be pinned by digest outside development")
    return issues
