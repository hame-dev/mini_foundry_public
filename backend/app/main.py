from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.actions.registry import load_user_workflows
from app.actions.router import router as actions_router, admin_router as actions_admin_router
from app.activity.router import router as activity_router
from app.applications.router import router as applications_router
from app.audit.router import router as audit_router
from app.ai.router import router as ai_router
from app.auth.admin_router import router as admin_users_router
from app.auth.router import router as auth_router
from app.auth.sso import router as sso_router
from app.auth.enterprise_router import router as enterprise_identity_router
from app.auth.token_router import router as token_router, admin_router as service_accounts_router
from app.auth.service import assign_role, create_user, get_or_create_role, get_user_by_email
from app.automation.router import router as automation_router
from app.config import get_settings, production_hardening_issues
from app.collaboration.router import router as collaboration_router
from app.connectors.router import router as connectors_router
from app.dashboards.router import router as dashboards_router
from app.data.router import router as data_router
from app.governance.router import router as governance_router
from app.governed_query.router import router as governed_query_router
from app.db import SessionLocal
from app.code_repo.router import router as code_repo_router
from app.explore.router import router as explore_router
from app.jobs.router import router as jobs_router, schedules_router
from app.operations.router import router as operations_router
from app.governance.admin_router import router as governance_admin_router
from app.media.router import router as media_router
from app.ml.router import router as ml_router
from app.notifications.router import router as notifications_router
from app.notebooks.router import router as notebooks_router
from app.ontology.router import (
    router as ontology_router,
    admin_router as ontology_admin_router,
    objects_router,
)
from app.permissions.router import router as permissions_router
from app.pipelines.router import router as pipelines_router
from app.platform.router import router as platform_router
from app.settings.router import router as settings_router
from app.timeseries.router import router as timeseries_router
from app.workspace.router import router as workspace_router
from app.observability import request_id_middleware
from app.rate_limit import rate_limit_middleware
from app.idempotency import idempotency_middleware


settings = get_settings()


async def seed_admin() -> None:
    async with SessionLocal() as session:
        existing = await get_user_by_email(session, settings.admin_email)
        if existing is not None:
            return
        user = await create_user(session, settings.admin_email, settings.admin_password, name="Admin")
        admin_role = await get_or_create_role(session, "admin")
        await assign_role(session, user.id, admin_role.id)
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    issues = production_hardening_issues(settings)
    if settings.environment == "production" and settings.require_production_hardening and issues:
        raise RuntimeError("production hardening checks failed: " + "; ".join(issues))
    try:
        await seed_admin()
    except Exception as e:
        # Don't crash the app if seeding fails (e.g. DB not yet migrated)
        print(f"[startup] seed_admin skipped: {e}")
    if settings.seed_demo_data:
        try:
            from app.seeds.demo import seed_demo
            async with SessionLocal() as session:
                summary = await seed_demo(session)
            if summary.get("created"):
                print(f"[startup] demo seed loaded: {summary}")
        except Exception as e:  # noqa: BLE001
            print(f"[startup] seed_demo skipped: {e}")
    try:
        from app.platform.service import sync_existing_resources
        async with SessionLocal() as session:
            await sync_existing_resources(session)
            await session.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[startup] sync_existing_resources skipped: {e}")
    try:
        load_user_workflows()
    except Exception as e:  # noqa: BLE001
        print(f"[startup] load_user_workflows skipped: {e}")
    yield


app = FastAPI(title="Mini Foundry", version="0.2.0", lifespan=lifespan)
app.middleware("http")(request_id_middleware)
app.middleware("http")(idempotency_middleware)
app.middleware("http")(rate_limit_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
for r in (
    auth_router, token_router, data_router, connectors_router, ai_router,
    dashboards_router, notebooks_router, jobs_router, schedules_router,
    permissions_router, admin_users_router, audit_router,
    ontology_router, ontology_admin_router, objects_router,
    actions_router, actions_admin_router,
    pipelines_router, explore_router, ml_router, workspace_router,
    code_repo_router, sso_router, enterprise_identity_router, governance_router, activity_router, settings_router,
    timeseries_router, platform_router,
    applications_router, operations_router, governance_admin_router, governed_query_router,
    notifications_router, service_accounts_router, automation_router, media_router,
    collaboration_router,
):
    app.include_router(r, prefix=API_PREFIX)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get(f"{API_PREFIX}/system/health")
async def system_health() -> dict:
    checks: dict[str, dict] = {}

    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = {"status": "ok"}
    except Exception as e:  # noqa: BLE001
        checks["postgres"] = {"status": "error", "detail": str(e)}

    try:
        from app.cache.redis_client import get_redis
        await get_redis().ping()
        checks["redis"] = {"status": "ok"}
    except Exception as e:  # noqa: BLE001
        checks["redis"] = {"status": "error", "detail": str(e)}

    checks["trino"] = {
        "status": "ok" if settings.trino_host else "not_configured",
        "detail": settings.trino_host or "Set TRINO_HOST to enable Spark/Trino routing.",
    }
    checks["spark"] = {
        "status": "ok" if (settings.spark_runner_type == "spark" and settings.spark_connect_url) else "not_configured",
        "detail": (
            f"Using Spark Connect at {settings.spark_connect_url}"
            if settings.spark_runner_type == "spark"
            else "Spark runner is routed to Trino (default). Set SPARK_RUNNER_TYPE to 'spark' to enable."
        ),
    }
    checks["ai"] = {
        "status": "ok" if settings.ollama_base_url or settings.gemini_api_key or settings.custom_ai_base_url else "not_configured"
    }
    try:
        from app.storage.fs import default_bucket_uri, get_fs
        uri = default_bucket_uri("_healthcheck")
        fs = get_fs(uri)
        parent = uri.rsplit("/", 1)[0]
        exists = fs.exists(parent) if parent else True
        checks["object_storage"] = {"status": "ok", "detail": parent, "exists": bool(exists)}
    except Exception as e:  # noqa: BLE001
        checks["object_storage"] = {"status": "error", "detail": str(e)}
    checks["worker"] = {"status": "not_configured", "detail": "Celery health ping is available through the operations console when workers are running."}
    overall = "ok" if all(c["status"] in {"ok", "not_configured"} for c in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}
