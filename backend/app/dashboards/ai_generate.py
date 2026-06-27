"""AI-assisted dashboard layout generation (README §29).

Reuses the existing AI gateway. The model is shown the component registry
and a list of datasets the user can use with AI, and is asked to return a
JSON object {title, description, layout}. The layout is then validated
against the registry and the dataset allowlist before being returned to the
caller. We do NOT persist — the user must click Save in the builder.
"""
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gateway
from app.auth.models import User
from app.dashboards.registry import COMPONENTS
from app.dashboards.validation import LayoutValidationError, validate_layout
from app.data.catalog import list_visible_datasets
from app.data.models import Dataset, DatasetColumn
from app.permissions.enforcement import effective_capabilities_for_object


SYSTEM_PROMPT = """You are a dashboard generator for Mini Foundry.

You will be given:
- A registry of allowed component types with their `bindings` and `config` schemas.
- A list of datasets the user is permitted to query with AI, each with columns.

Rules:
- Output ONLY valid JSON: {"title": str, "description": str, "layout": {...}}.
- layout.version MUST equal 1.
- Every component MUST use a component_type that exists in the registry.
- Every component MUST have position {x, y, w, h} (integers, grid units, w/h <= 12).
- Every chart/metric/table MUST have a data_binding referencing a dataset_id from the allowlist.
- Only generate SELECT statements in sql_query bindings.
- Do not invent column names that are not in the provided dataset schemas.
"""


class AIDashboardError(ValueError):
    pass


async def _permitted_datasets_for_ai(
    session: AsyncSession, user: User, provider: str, dataset_ids: list[uuid.UUID] | None
) -> list[Dataset]:
    visible = await list_visible_datasets(session, user.id)
    if dataset_ids:
        wanted = set(dataset_ids)
        visible = [d for d in visible if d.id in wanted]

    permitted: list[Dataset] = []
    for d in visible:
        if d.owner_id == user.id:
            permitted.append(d)
            continue
        caps = await effective_capabilities_for_object(session, user, "dataset", d.id)
        if "use_with_ai" in caps or "manage" in caps:
            permitted.append(d)

    for d in permitted:
        gateway.enforce_ai_policy(d, provider)
    return permitted


async def _columns_for(session: AsyncSession, dataset_ids: list[uuid.UUID]) -> dict[str, list[DatasetColumn]]:
    if not dataset_ids:
        return {}
    rows_q = await session.execute(
        select(DatasetColumn).where(DatasetColumn.dataset_id.in_(dataset_ids))
    )
    out: dict[str, list[DatasetColumn]] = {}
    for c in rows_q.scalars().all():
        out.setdefault(str(c.dataset_id), []).append(c)
    return out


def _registry_summary() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, spec in COMPONENTS.items():
        out[name] = {
            "bindings": sorted(spec["bindings"]),
            "required_config": {
                k: (sorted(v) if isinstance(v, set) else getattr(v, "__name__", str(v)))
                for k, v in spec["required"].items()
            },
        }
    return out


def _allowlist_summary(datasets: list[Dataset], columns_by_id: dict[str, list[DatasetColumn]]) -> list[dict]:
    out: list[dict] = []
    for d in datasets:
        out.append({
            "dataset_id": str(d.id),
            "name": d.name,
            "schema": d.schema_name,
            "table": d.table_name,
            "columns": [
                {"name": c.name, "type": c.data_type} for c in columns_by_id.get(str(d.id), [])
            ],
        })
    return out


def _check_referenced_datasets(layout: dict, permitted_ids: set[str]) -> None:
    for i, c in enumerate(layout.get("components", [])):
        binding = c.get("data_binding") or {}
        btype = binding.get("type")
        if btype == "dataset":
            did = binding.get("dataset_id")
            if did not in permitted_ids:
                raise LayoutValidationError(
                    f"components[{i}].data_binding.dataset_id: dataset {did} not in permitted allowlist"
                )
        elif btype == "sql_query":
            for did in binding.get("dataset_ids", []):
                if did not in permitted_ids:
                    raise LayoutValidationError(
                        f"components[{i}].data_binding.dataset_ids: dataset {did} not in permitted allowlist"
                    )


def _parse_ai_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AIDashboardError(f"AI did not return valid JSON: {e}")


async def generate_dashboard_layout(
    *,
    session: AsyncSession,
    user: User,
    prompt: str,
    provider: str,
    model: str | None,
    dataset_ids: list[uuid.UUID] | None,
) -> dict:
    """Returns {title, description, layout} after full validation. Raises
    AIDashboardError / LayoutValidationError / AIPolicyError on failure.
    """
    permitted = await _permitted_datasets_for_ai(session, user, provider, dataset_ids)
    if not permitted:
        raise AIDashboardError("no datasets permitted for AI use")

    columns_by_id = await _columns_for(session, [d.id for d in permitted])

    user_msg = (
        "Component registry (allowed types and their config keys):\n"
        + json.dumps(_registry_summary(), indent=2)
        + "\n\nPermitted datasets (you may only reference these dataset_ids):\n"
        + json.dumps(_allowlist_summary(permitted, columns_by_id), indent=2)
        + f"\n\nUser request: {prompt}\n\nReply with JSON {{title, description, layout}}."
    )

    result = await gateway.generate(
        session=session,
        provider=provider,
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        datasets=permitted,
        response_format="json",
    )

    parsed = _parse_ai_response(result["text"])
    if not isinstance(parsed, dict):
        raise AIDashboardError("AI response is not an object")

    layout = parsed.get("layout")
    if not isinstance(layout, dict):
        raise AIDashboardError("AI response missing 'layout' object")

    validate_layout(layout)
    _check_referenced_datasets(layout, {str(d.id) for d in permitted})

    return {
        "title": str(parsed.get("title") or "Untitled dashboard"),
        "description": str(parsed.get("description") or "") or None,
        "layout": layout,
    }
