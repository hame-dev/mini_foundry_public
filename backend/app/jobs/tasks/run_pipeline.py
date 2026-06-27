import asyncio
import uuid
from typing import Any

from app.db import SessionLocal
from app.jobs.registry import job_task
from app.pipelines.models import Pipeline
from app.pipelines.service import run


@job_task("run_pipeline")
def run_pipeline(session, job, input: dict[str, Any]) -> dict[str, Any]:
    pipeline_id = uuid.UUID(input["pipeline_id"])
    user_id = uuid.UUID(input["user_id"])

    async def _execute() -> dict[str, Any]:
        async with SessionLocal() as async_session:
            pipeline = await async_session.get(Pipeline, pipeline_id)
            if pipeline is None:
                raise ValueError(f"Pipeline {pipeline_id} not found")
            pipeline.last_run_status = "running"
            await async_session.commit()
            result = await run(async_session, user_id, pipeline)
            await async_session.commit()
            return result

    try:
        result = asyncio.run(_execute())
        if result.get("status") == "error":
            raise RuntimeError(result.get("error", "Run failed"))
        return result
    except Exception as e:
        pipeline = session.get(Pipeline, pipeline_id)
        if pipeline is not None:
            pipeline.last_run_status = "error"
            pipeline.last_run_error = str(e)
            session.commit()
        raise
