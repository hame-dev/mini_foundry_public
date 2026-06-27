import re
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.ai import gateway, sql_prompt
from app.ai.models import AiEvaluation, PromptTemplate
from app.audit.logger import log_event
from app.auth.service import get_user_roles
from app.data.catalog import list_visible_datasets
from app.data.models import Dataset, DatasetColumn
from app.deps import AdminDep, CurrentUserDep, SessionDep
from app.execution.sql_runner import pick_engine
from app.execution.sql_validator import SqlValidationError
from app.governed_query.service import governed_query, resolve_datasets_for_sql
from app.governance.models import UsageMetric
from app.permissions.enforcement import (
    PermissionDenied,
    get_permission_version,
    policy_cache_versions,
    require_object_capability,
)
from app.platform.service import get_resource_for_object, latest_dataset_version, record_lineage
from app.cache.sql_cache import cache_key_for_sql, get_cached_result, set_cached_result
from app.platform.models import AiRun, AiToolCall

router = APIRouter(prefix="/ai", tags=["ai"])


class AIProviderInfo(BaseModel):
    name: str
    label: str
    default_model: str
    configured: bool
    local: bool


@router.get("/providers", response_model=list[AIProviderInfo])
async def list_ai_providers(user: CurrentUserDep) -> list[AIProviderInfo]:  # noqa: ARG001
    from app.config import get_settings

    s = get_settings()
    return [
        AIProviderInfo(
            name="ollama",
            label="Ollama (local)",
            default_model=s.ollama_default_model,
            configured=bool(s.ollama_base_url),
            local=True,
        ),
        AIProviderInfo(
            name="gemini",
            label="Gemini",
            default_model=s.gemini_default_model,
            configured=bool(s.gemini_api_key),
            local=False,
        ),
        AIProviderInfo(
            name="openai_compatible",
            label="OpenAI compatible",
            default_model=s.custom_ai_default_model,
            configured=bool(s.custom_ai_base_url),
            local=False,
        ),
    ]


class AiSqlIn(BaseModel):
    question: str
    provider: str = "ollama"
    model: str | None = None
    dataset_ids: list[uuid.UUID] | None = None  # if None, all permitted datasets


class AiSqlOut(BaseModel):
    sql: str
    explanation: str
    confidence: float
    provider: str
    model: str
    dataset_ids: list[str]


class RunSqlIn(BaseModel):
    sql: str
    dataset_ids: list[uuid.UUID]
    query_id: str | None = None


_USER_PLACEHOLDER_RE = re.compile(r"\{\{\s*user\.(id|email|name)\s*\}\}", re.IGNORECASE)
_LEGACY_USERNAME_RE = re.compile(r"(?<![A-Za-z0-9_])USERNAME(?![A-Za-z0-9_])")


def _sql_literal(value: str | None) -> str:
    return "'" + (value or "").replace("'", "''") + "'"


def _resolve_user_placeholders(sql: str, user) -> str:
    def repl(match: re.Match[str]) -> str:
        field = match.group(1).lower()
        if field == "id":
            return _sql_literal(str(user.id))
        if field == "email":
            return _sql_literal(user.email)
        if field == "name":
            return _sql_literal(user.name or user.email)
        raise ValueError(f"missing placeholder user.{field}")

    resolved = _USER_PLACEHOLDER_RE.sub(repl, sql)
    return _LEGACY_USERNAME_RE.sub(_sql_literal(user.email or user.name), resolved)


def _sql_error(status_code: int, code: str, phase: str, message: str, resolved_sql: str | None = None) -> HTTPException:
    detail: dict[str, str] = {"code": code, "phase": phase, "message": message}
    if resolved_sql is not None:
        detail["resolved_sql"] = resolved_sql
    return HTTPException(status_code=status_code, detail=detail)


@router.post("/sql", response_model=AiSqlOut)
async def ai_sql(payload: AiSqlIn, session: SessionDep, user: CurrentUserDep) -> AiSqlOut:
    visible = await list_visible_datasets(session, user.id)
    if payload.dataset_ids:
        wanted = set(payload.dataset_ids)
        datasets = [d for d in visible if d.id in wanted]
        visible_ids = {d.id for d in datasets}
        missing = wanted - visible_ids
        if missing:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"datasets not permitted for AI use: {', '.join(str(x) for x in sorted(missing, key=str))}")
    else:
        datasets = visible

    permitted: list[Dataset] = []
    for d in datasets:
        try:
            await require_object_capability(session, user, "dataset", d.id, "use_with_ai")
            permitted.append(d)
        except PermissionDenied:
            if payload.dataset_ids:
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"dataset {d.id}: missing capability: use_with_ai")
            continue

    if not permitted:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no datasets permitted for AI use")

    # Enforce per-dataset AI policy
    for d in permitted:
        try:
            gateway.enforce_ai_policy(d, payload.provider)
        except gateway.AIPolicyError as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))

    cols_q = await session.execute(
        select(DatasetColumn).where(DatasetColumn.dataset_id.in_([d.id for d in permitted]))
    )
    cols_by_dataset: dict[str, list[DatasetColumn]] = {}
    for c in cols_q.scalars().all():
        cols_by_dataset.setdefault(str(c.dataset_id), []).append(c)

    messages = sql_prompt.build_messages(payload.question, permitted, cols_by_dataset)
    model = payload.model or gateway.default_model_for(payload.provider)
    ai_run = AiRun(
        user_id=user.id,
        provider=payload.provider,
        model=model,
        policy=max((d.ai_policy for d in permitted), default="local_only"),
        prompt_template="ai_sql",
        token_estimate=sum(len(str(m.get("content", ""))) for m in messages) // 4,
    )
    session.add(ai_run)
    await session.flush()

    try:
        result = await gateway.generate(
            session=session,
            provider=payload.provider,
            model=model,
            messages=messages,
            datasets=permitted,
            response_format="json",
        )
    except Exception as e:
        ai_run.status = "failed"
        await session.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"AI provider error: {e}")

    parsed = sql_prompt.parse_response(result["text"])
    session.add(AiToolCall(
        ai_run_id=ai_run.id,
        tool_name="generate_sql_draft",
        input={"dataset_ids": [str(d.id) for d in permitted]},
        output_summary={"confidence": parsed["confidence"]},
    ))
    for d in permitted:
        resource = await get_resource_for_object(session, "dataset", d.id)
        if resource is not None:
            await record_lineage(
                session,
                source_resource_id=resource.id,
                target_resource_id=None,
                edge_type="dataset_to_ai_run",
                metadata={"ai_run_id": str(ai_run.id), "tool_name": "generate_sql_draft", "branch_name": getattr(d, "branch_name", "main") or "main"},
            )

    await log_event(
        session, user=user, event_type="AI_PROVIDER_USED",
        resource_type="ai_sql", provider=payload.provider,
        input_summary={"question": payload.question, "model": model,
                       "dataset_ids": [str(d.id) for d in permitted]},
        output_summary={"sql": parsed["sql"], "confidence": parsed["confidence"]},
    )
    await session.commit()
    return AiSqlOut(
        sql=parsed["sql"],
        explanation=parsed["explanation"],
        confidence=parsed["confidence"],
        provider=payload.provider,
        model=model,
        dataset_ids=[str(d.id) for d in permitted],
    )


@router.post("/run-sql")
async def run_validated_sql(payload: RunSqlIn, session: SessionDep, user: CurrentUserDep) -> dict:
    try:
        resolved_sql = _resolve_user_placeholders(payload.sql, user)
    except ValueError as e:
        raise _sql_error(status.HTTP_400_BAD_REQUEST, "missing_placeholder", "validation", str(e))

    version = await get_permission_version(session)
    # Build a cache key that includes the resolved dataset versions and target
    # engine so cached results are invalidated when underlying data or routing
    # changes. branch is "main" until branch-aware editing lands; row/mask policy
    # versions default to the global permission version inside the helper.
    try:
        datasets = await resolve_datasets_for_sql(session, resolved_sql, payload.dataset_ids)
    except PermissionDenied as e:
        raise _sql_error(status.HTTP_403_FORBIDDEN, "permission_denied", "authorization", str(e), resolved_sql)
    from app.config import get_settings
    settings = get_settings()
    since = datetime.utcnow() - timedelta(days=1)
    used = (
        await session.execute(
            select(func.coalesce(func.sum(UsageMetric.compute_credits), 0.0)).where(
                UsageMetric.user_id == user.id,
                UsageMetric.resource_type == "sql",
                UsageMetric.created_at >= since,
            )
        )
    ).scalar() or 0.0
    if settings.sql_daily_user_credit_quota > 0 and float(used) >= settings.sql_daily_user_credit_quota:
        raise _sql_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "quota_exceeded",
            "quota",
            "daily SQL compute quota exceeded",
            resolved_sql,
        )
    dataset_version_ids: list[str] = []
    for ds in datasets:
        ds_version = await latest_dataset_version(session, ds.id)
        if ds_version:
            dataset_version_ids.append(str(ds_version.id))
    engine = pick_engine(datasets)
    row_policy_version, mask_policy_version = await policy_cache_versions(session, [ds.id for ds in datasets])
    key = cache_key_for_sql(
        str(user.id),
        resolved_sql,
        version,
        dataset_version_ids=dataset_version_ids,
        engine=engine,
        row_policy_version=row_policy_version,
        mask_policy_version=mask_policy_version,
    )
    cached = await get_cached_result(key)
    if cached:
        return {"cached": True, "phase": "cache", "resolved_sql": resolved_sql, "query_id": payload.query_id, **cached}

    import time
    start_time = time.perf_counter()
    try:
        result = await governed_query(
            session,
            user,
            resolved_sql,
            dataset_ids=payload.dataset_ids,
            capability="use_in_sql",
            audit_resource_type="ai_sql",
            query_id=payload.query_id,
        )
    except SqlValidationError as e:
        raise _sql_error(status.HTTP_400_BAD_REQUEST, "sql_invalid", "validation", str(e), resolved_sql)
    except PermissionDenied as e:
        raise _sql_error(status.HTTP_403_FORBIDDEN, "permission_denied", "authorization", str(e), resolved_sql)
    except Exception as e:
        raise _sql_error(status.HTTP_400_BAD_REQUEST, "execution_failed", "engine_execution", str(e), resolved_sql)
    
    execution_time_ms = int((time.perf_counter() - start_time) * 1000)

    cacheable = {k: v for k, v in result.items() if k not in {"rewritten_sql"}}
    await set_cached_result(key, cacheable, ttl_seconds=300)
    ai_run = AiRun(
        user_id=user.id,
        provider="backend",
        model="governed_query",
        policy="local_only",
        prompt_template="run_sql_tool",
        token_estimate=len(resolved_sql) // 4,
    )
    session.add(ai_run)
    await session.flush()
    session.add(AiToolCall(
        ai_run_id=ai_run.id,
        tool_name="query_dataset",
        input={"dataset_ids": [str(x) for x in payload.dataset_ids]},
        output_summary={"row_count": cacheable.get("row_count"), "query_hash": cacheable.get("query_hash")},
    ))
    for ds in datasets:
        resource = await get_resource_for_object(session, "dataset", ds.id)
        if resource is not None:
            await record_lineage(
                session,
                source_resource_id=resource.id,
                target_resource_id=None,
                edge_type="dataset_to_ai_tool_call",
                metadata={
                    "ai_run_id": str(ai_run.id),
                    "tool_name": "query_dataset",
                    "query_hash": cacheable.get("query_hash"),
                    "branch_name": getattr(ds, "branch_name", "main") or "main",
                },
            )
    from app.governance.service import track_usage
    await track_usage(session, user.id, "sql", execution_time_ms)
    await session.commit()
    return {"cached": False, "phase": "engine_execution", "resolved_sql": resolved_sql, "query_id": payload.query_id, **cacheable}


class LogicStep(BaseModel):
    type: str  # "llm" or "sql" or "template"
    prompt: str | None = None
    provider: str | None = "ollama"
    model: str | None = None
    query: str | None = None
    template: str | None = None
    output_var: str


class AIPLogicPayload(BaseModel):
    inputs: dict[str, str]
    steps: list[LogicStep]


def render_logic_template(tmpl: str, context: dict) -> str:
    import re
    def repl(m):
        path = m.group(1).strip().split(".")
        val = context
        for key in path:
            if isinstance(val, dict) and key in val:
                val = val[key]
            else:
                return m.group(0)
        return str(val)
    return re.sub(r"\{\{([^}]+)\}\}", repl, tmpl)


@router.post("/logic/run")
async def run_aip_logic(
    payload: AIPLogicPayload,
    session: SessionDep,
    user: CurrentUserDep
) -> dict:
    import time

    context = {
        "inputs": payload.inputs,
        "steps": {}
    }
    
    execution_log = []
    start_time = time.perf_counter()

    for idx, step in enumerate(payload.steps):
        step_log = {"type": step.type, "output_var": step.output_var}
        try:
            if step.type == "template":
                if not step.template:
                    raise ValueError("Template step requires template string")
                rendered = render_logic_template(step.template, context)
                context["steps"][step.output_var] = rendered
                step_log["output"] = rendered

            elif step.type == "llm":
                if not step.prompt:
                    raise ValueError("LLM step requires prompt")
                rendered_prompt = render_logic_template(step.prompt, context)
                messages = [{"role": "user", "content": rendered_prompt}]
                prov = step.provider or "ollama"
                model = step.model or gateway.default_model_for(prov)
                
                res = await gateway.generate(
                    session=session,
                    provider=prov,
                    model=model,
                    messages=messages,
                    datasets=[],
                    response_format="text"
                )
                txt = res["text"]
                context["steps"][step.output_var] = txt
                step_log["output"] = txt
                step_log["prompt_used"] = rendered_prompt

            elif step.type == "sql":
                if not step.query:
                    raise ValueError("SQL step requires query")
                rendered_sql = render_logic_template(step.query, context)

                # Route through the governed query service so the SQL step gets
                # the same capability checks, row-policy rewrite + revalidation,
                # masking, dataset-version capture, and audit shape as other
                # governed SQL paths instead of calling run_sql directly.
                result = await governed_query(
                    session,
                    user,
                    rendered_sql,
                    capability="use_with_ai",
                    audit_resource_type="ai_logic",
                )
                out_data = {
                    "rows": result["rows"],
                    "row_count": result["row_count"],
                    "columns": result["columns"],
                }
                context["steps"][step.output_var] = out_data
                step_log["output"] = out_data
                step_log["query_used"] = rendered_sql
            else:
                raise ValueError(f"Unknown step type: {step.type}")
        except Exception as e:
            step_log["error"] = str(e)
            execution_log.append(step_log)
            
            # Save partial usage metric even on failure
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            from app.governance.service import track_usage
            await track_usage(session, user.id, "ai_logic", execution_time_ms)
            await session.commit()

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": f"Error running step '{step.output_var}': {e}", "log": execution_log}
            )
        execution_log.append(step_log)

    execution_time_ms = int((time.perf_counter() - start_time) * 1000)
    from app.governance.service import track_usage
    await track_usage(session, user.id, "ai_logic", execution_time_ms)
    await session.commit()

    return {"status": "success", "context": context, "execution_log": execution_log}


# ===========================================================================
# AI console: runs, tool-calls, usage, prompt templates, evaluations
# ===========================================================================


async def _is_admin(session, user) -> bool:
    return "admin" in await get_user_roles(session, user.id)


# --------------------------------------------------------------------- runs

class AiRunOut(BaseModel):
    id: str
    user_id: str | None
    provider: str | None
    model: str | None
    policy: str
    prompt_template: str | None
    status: str
    token_estimate: int | None
    created_at: datetime


class AiToolCallOut(BaseModel):
    id: str
    ai_run_id: str | None
    tool_name: str
    input: dict | None
    output_summary: dict | None
    status: str
    created_at: datetime


class AiRunDetailOut(AiRunOut):
    tool_calls: list[AiToolCallOut]


def _run_out(r: AiRun) -> AiRunOut:
    return AiRunOut(
        id=str(r.id), user_id=str(r.user_id) if r.user_id else None,
        provider=r.provider, model=r.model, policy=r.policy,
        prompt_template=r.prompt_template, status=r.status,
        token_estimate=r.token_estimate, created_at=r.created_at,
    )


def _tool_call_out(t: AiToolCall) -> AiToolCallOut:
    return AiToolCallOut(
        id=str(t.id), ai_run_id=str(t.ai_run_id) if t.ai_run_id else None,
        tool_name=t.tool_name, input=t.input, output_summary=t.output_summary,
        status=t.status, created_at=t.created_at,
    )


@router.get("/runs", response_model=list[AiRunOut])
async def list_ai_runs(
    session: SessionDep, user: CurrentUserDep,
    provider: str | None = None, status_filter: str | None = None,
    limit: int = Query(100, le=500),
) -> list[AiRunOut]:
    stmt = select(AiRun).order_by(AiRun.created_at.desc())
    if not await _is_admin(session, user):
        stmt = stmt.where(AiRun.user_id == user.id)
    if provider:
        stmt = stmt.where(AiRun.provider == provider)
    if status_filter:
        stmt = stmt.where(AiRun.status == status_filter)
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return [_run_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=AiRunDetailOut)
async def get_ai_run(run_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> AiRunDetailOut:
    run = await session.get(AiRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    if run.user_id != user.id and not await _is_admin(session, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your run")
    calls = (await session.execute(
        select(AiToolCall).where(AiToolCall.ai_run_id == run_id).order_by(AiToolCall.created_at)
    )).scalars().all()
    return AiRunDetailOut(**_run_out(run).model_dump(), tool_calls=[_tool_call_out(c) for c in calls])


@router.get("/tool-calls", response_model=list[AiToolCallOut])
async def list_ai_tool_calls(session: SessionDep, user: CurrentUserDep, limit: int = Query(100, le=500)) -> list[AiToolCallOut]:
    # Scope to the caller's runs unless admin.
    stmt = select(AiToolCall).order_by(AiToolCall.created_at.desc())
    if not await _is_admin(session, user):
        stmt = stmt.join(AiRun, AiRun.id == AiToolCall.ai_run_id).where(AiRun.user_id == user.id)
    rows = (await session.execute(stmt.limit(limit))).scalars().all()
    return [_tool_call_out(t) for t in rows]


# --------------------------------------------------------------------- usage

class AiUsageRowOut(BaseModel):
    provider: str | None
    model: str | None
    run_count: int
    token_total: int


class AiUsageOut(BaseModel):
    window_hours: int
    total_runs: int
    total_tokens: int
    by_provider_model: list[AiUsageRowOut]
    credits: float
    latency_ms_avg: float


@router.get("/usage", response_model=AiUsageOut)
async def ai_usage(session: SessionDep, user: CurrentUserDep, window_hours: int = 24) -> AiUsageOut:
    since = datetime.utcnow() - timedelta(hours=window_hours)
    admin = await _is_admin(session, user)

    run_stmt = (
        select(AiRun.provider, AiRun.model, func.count(), func.coalesce(func.sum(AiRun.token_estimate), 0))
        .where(AiRun.created_at >= since)
        .group_by(AiRun.provider, AiRun.model)
        .order_by(func.count().desc())
    )
    if not admin:
        run_stmt = run_stmt.where(AiRun.user_id == user.id)
    rows = (await session.execute(run_stmt)).all()
    by_pm = [AiUsageRowOut(provider=p, model=m, run_count=int(c), token_total=int(tok)) for p, m, c, tok in rows]
    total_runs = sum(r.run_count for r in by_pm)
    total_tokens = sum(r.token_total for r in by_pm)

    um_stmt = select(
        func.coalesce(func.sum(UsageMetric.compute_credits), 0.0),
        func.coalesce(func.avg(UsageMetric.execution_time_ms), 0.0),
    ).where(UsageMetric.created_at >= since, UsageMetric.resource_type.like("ai%"))
    if not admin:
        um_stmt = um_stmt.where(UsageMetric.user_id == user.id)
    credits, latency = (await session.execute(um_stmt)).one()

    return AiUsageOut(
        window_hours=window_hours, total_runs=total_runs, total_tokens=total_tokens,
        by_provider_model=by_pm, credits=float(credits or 0), latency_ms_avg=float(latency or 0),
    )


# ----------------------------------------------------------- prompt templates

class PromptIn(BaseModel):
    name: str
    description: str | None = None
    template: str


class PromptOut(BaseModel):
    id: str
    name: str
    description: str | None
    template: str
    version: int
    created_at: datetime | None


def _prompt_out(p: PromptTemplate) -> PromptOut:
    return PromptOut(
        id=str(p.id), name=p.name, description=p.description,
        template=p.template, version=p.version, created_at=p.created_at,
    )


_REDACTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("api_key", re.compile(r"\b(?:sk|pk|api|key|token)[_-]?[A-Za-z0-9]{20,}\b", re.IGNORECASE)),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)),
    ("phone", re.compile(r"\b(?:\+?\d[\d .-]{7,}\d)\b")),
]


class PromptPreviewIn(BaseModel):
    prompt_template_id: uuid.UUID | None = None
    template: str | None = None
    context: dict | None = None
    dataset_ids: list[uuid.UUID] | None = None


class PromptRedactionOut(BaseModel):
    type: str
    count: int


class PromptPreviewOut(BaseModel):
    rendered_prompt: str
    redacted_prompt: str
    redactions: list[PromptRedactionOut]
    permission_notices: list[str]


def _redact_prompt(text: str) -> tuple[str, list[PromptRedactionOut]]:
    redacted = text
    redactions: list[PromptRedactionOut] = []
    for label, pattern in _REDACTION_PATTERNS:
        count = 0

        def repl(_: re.Match[str]) -> str:
            nonlocal count
            count += 1
            return f"[REDACTED:{label}]"

        redacted = pattern.sub(repl, redacted)
        if count:
            redactions.append(PromptRedactionOut(type=label, count=count))
    return redacted, redactions


@router.post("/prompts/preview", response_model=PromptPreviewOut)
async def preview_prompt(payload: PromptPreviewIn, session: SessionDep, user: CurrentUserDep) -> PromptPreviewOut:
    template = payload.template
    if payload.prompt_template_id is not None:
        tpl = await session.get(PromptTemplate, payload.prompt_template_id)
        if tpl is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "prompt template not found")
        template = tpl.template
    if not template or not template.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "template or prompt_template_id is required")

    permission_notices: list[str] = []
    if payload.dataset_ids:
        for dataset_id in payload.dataset_ids:
            dataset = await session.get(Dataset, dataset_id)
            if dataset is None:
                permission_notices.append(f"dataset {dataset_id} not found")
                continue
            try:
                await require_object_capability(session, user, "dataset", dataset.id, "use_with_ai")
            except PermissionDenied:
                permission_notices.append(f"dataset {dataset_id} is not permitted for AI use")

    rendered = render_logic_template(template, payload.context or {})
    redacted, redactions = _redact_prompt(rendered)
    await log_event(
        session,
        user=user,
        event_type="AI_PROMPT_PREVIEWED",
        resource_type="prompt_template",
        resource_id=str(payload.prompt_template_id) if payload.prompt_template_id else None,
        input_summary={"has_template_id": payload.prompt_template_id is not None, "dataset_count": len(payload.dataset_ids or [])},
        output_summary={"redaction_count": sum(r.count for r in redactions), "permission_notice_count": len(permission_notices)},
    )
    await session.commit()
    return PromptPreviewOut(
        rendered_prompt=rendered,
        redacted_prompt=redacted,
        redactions=redactions,
        permission_notices=permission_notices,
    )


@router.get("/prompts", response_model=list[PromptOut])
async def list_prompts(session: SessionDep, _: CurrentUserDep) -> list[PromptOut]:
    rows = (await session.execute(select(PromptTemplate).order_by(PromptTemplate.name, PromptTemplate.version.desc()))).scalars().all()
    return [_prompt_out(p) for p in rows]


@router.post("/prompts", response_model=PromptOut)
async def create_prompt(payload: PromptIn, session: SessionDep, admin: AdminDep) -> PromptOut:
    if not payload.name.strip() or not payload.template.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "name and template are required")
    # Version bump: next version for this name.
    max_v = (await session.execute(
        select(func.max(PromptTemplate.version)).where(PromptTemplate.name == payload.name)
    )).scalar()
    tpl = PromptTemplate(
        name=payload.name.strip(), description=payload.description,
        template=payload.template, version=int(max_v or 0) + 1, created_by=admin.id,
    )
    session.add(tpl)
    await session.flush()
    await log_event(session, user=admin, event_type="AI_PROMPT_EDITED", resource_type="prompt_template",
                    resource_id=str(tpl.id), input_summary={"name": tpl.name, "version": tpl.version})
    await session.commit()
    return _prompt_out(tpl)


@router.get("/prompts/{prompt_id}", response_model=PromptOut)
async def get_prompt(prompt_id: uuid.UUID, session: SessionDep, _: CurrentUserDep) -> PromptOut:
    tpl = await session.get(PromptTemplate, prompt_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "prompt template not found")
    return _prompt_out(tpl)


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    tpl = await session.get(PromptTemplate, prompt_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "prompt template not found")
    await session.delete(tpl)
    await log_event(session, user=admin, event_type="AI_PROMPT_EDITED", resource_type="prompt_template",
                    resource_id=str(prompt_id), input_summary={"action": "delete"})
    await session.commit()
    return {"ok": True}


# -------------------------------------------------------------- evaluations

class EvaluationIn(BaseModel):
    name: str
    description: str | None = None
    prompt_template_id: uuid.UUID | None = None
    provider: str | None = None
    model: str | None = None
    cases: dict | None = None
    score: float | None = None
    results: dict | None = None
    status: str = "draft"


class EvaluationOut(BaseModel):
    id: str
    name: str
    description: str | None
    prompt_template_id: str | None
    provider: str | None
    model: str | None
    cases: dict | None
    score: float | None
    results: dict | None
    status: str
    created_at: datetime | None


def _eval_out(e: AiEvaluation) -> EvaluationOut:
    return EvaluationOut(
        id=str(e.id), name=e.name, description=e.description,
        prompt_template_id=str(e.prompt_template_id) if e.prompt_template_id else None,
        provider=e.provider, model=e.model, cases=e.cases, score=e.score,
        results=e.results, status=e.status, created_at=e.created_at,
    )


@router.get("/evaluations", response_model=list[EvaluationOut])
async def list_evaluations(session: SessionDep, _: CurrentUserDep) -> list[EvaluationOut]:
    rows = (await session.execute(select(AiEvaluation).order_by(AiEvaluation.created_at.desc()))).scalars().all()
    return [_eval_out(e) for e in rows]


@router.post("/evaluations", response_model=EvaluationOut)
async def create_evaluation(payload: EvaluationIn, session: SessionDep, admin: AdminDep) -> EvaluationOut:
    if not payload.name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "name is required")
    ev = AiEvaluation(
        name=payload.name.strip(), description=payload.description,
        prompt_template_id=payload.prompt_template_id, provider=payload.provider,
        model=payload.model, cases=payload.cases, score=payload.score,
        results=payload.results, status=payload.status, created_by=admin.id,
    )
    session.add(ev)
    await session.flush()
    await log_event(session, user=admin, event_type="AI_EVALUATION_EDITED", resource_type="ai_evaluation",
                    resource_id=str(ev.id), input_summary={"name": ev.name})
    await session.commit()
    return _eval_out(ev)


@router.get("/evaluations/{eval_id}", response_model=EvaluationOut)
async def get_evaluation(eval_id: uuid.UUID, session: SessionDep, _: CurrentUserDep) -> EvaluationOut:
    ev = await session.get(AiEvaluation, eval_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "evaluation not found")
    return _eval_out(ev)


@router.delete("/evaluations/{eval_id}")
async def delete_evaluation(eval_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> dict:
    ev = await session.get(AiEvaluation, eval_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "evaluation not found")
    await session.delete(ev)
    await log_event(session, user=admin, event_type="AI_EVALUATION_EDITED", resource_type="ai_evaluation",
                    resource_id=str(eval_id), input_summary={"action": "delete"})
    await session.commit()
    return {"ok": True}


@router.post("/evaluations/{eval_id}/run", response_model=EvaluationOut)
async def run_evaluation(eval_id: uuid.UUID, session: SessionDep, admin: AdminDep) -> EvaluationOut:
    ev = await session.get(AiEvaluation, eval_id)
    if ev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "evaluation not found")

    tpl: PromptTemplate | None = None
    if ev.prompt_template_id is not None:
        tpl = await session.get(PromptTemplate, ev.prompt_template_id)

    raw_cases = ev.cases or {}
    if isinstance(raw_cases, dict) and isinstance(raw_cases.get("cases"), list):
        cases = raw_cases["cases"]
    elif isinstance(raw_cases, list):
        cases = raw_cases
    else:
        cases = []

    results: list[dict] = []
    scored = 0
    passed = 0
    for index, case in enumerate(cases):
        case_dict = case if isinstance(case, dict) else {"input": case}
        context = case_dict.get("context") or case_dict.get("input") or {}
        template = str(case_dict.get("template") or (tpl.template if tpl is not None else ""))
        rendered = render_logic_template(template, context if isinstance(context, dict) else {"input": context})
        redacted, redactions = _redact_prompt(rendered)
        expected = case_dict.get("expected_contains")
        case_passed = True
        if expected:
            scored += 1
            expected_values = expected if isinstance(expected, list) else [expected]
            case_passed = all(str(value) in redacted for value in expected_values)
            if case_passed:
                passed += 1
        results.append({
            "index": index,
            "status": "passed" if case_passed else "failed",
            "redaction_count": sum(r.count for r in redactions),
            "expected_checked": bool(expected),
        })

    ev.status = "completed"
    ev.score = (passed / scored) if scored else 1.0
    ev.results = {
        "mode": "deterministic_prompt_governance",
        "case_count": len(cases),
        "scored_case_count": scored,
        "passed_case_count": passed,
        "cases": results,
    }
    await log_event(
        session,
        user=admin,
        event_type="AI_EVALUATION_RUN",
        resource_type="ai_evaluation",
        resource_id=str(ev.id),
        output_summary={"score": ev.score, "case_count": len(cases)},
    )
    await session.commit()
    return _eval_out(ev)
