import os

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="set RUN_INTEGRATION=1 with Postgres and Redis running",
)


def test_postgres_and_redis_are_reachable():
    from sqlalchemy import create_engine, text
    import redis

    from app.config import get_settings

    settings = get_settings()
    engine = create_engine(settings.sync_database_url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1

    client = redis.Redis.from_url(settings.redis_url)
    assert client.ping() is True


@pytest.mark.asyncio
async def test_fastapi_health_endpoint_reports_stack():
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/system/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert "postgres" in body["checks"]
    assert "redis" in body["checks"]
