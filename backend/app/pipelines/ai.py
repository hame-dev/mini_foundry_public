"""AI-assisted pipeline graph generation.

Asks the configured LLM to emit a node/edge JSON given the user's prompt
and the schemas of datasets the user is permitted to use with AI. The
returned graph is validated and *not* persisted — the user must hit Save.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import gateway
from app.auth.models import User
from app.data.catalog import list_visible_datasets
from app.data.models import Dataset, DatasetColumn
from app.permissions.enforcement import effective_capabilities_for_object
from app.pipelines.compiler import PipelineCompileError, compile_pipeline


SYSTEM_PROMPT = """You are a data-pipeline generator for Mini Foundry.

You will be given:
- A list of datasets the user can use with AI, each with columns.
- Optionally, the user's natural-language description of the pipeline they want.

You must reply with ONLY a JSON object of shape:
{
  "name": str,
  "description": str | null,
  "nodes": [{"id": str, "node_type": "source|join|union|filter|formula|select|output",
             "position": {"x": number, "y": number}, "config": {...}}],
  "edges": [{"id": str, "source_node_id": str, "target_node_id": str,
             "target_handle": "left|right|in"}]
}

Rules:
- Use only the dataset_ids from the permitted list in source nodes' config.dataset_id.
- Every pipeline MUST contain exactly one node with node_type == "output".
- Join nodes need exactly two inputs with target_handle "left" and "right",
  and config with left_keys / right_keys / join_type.
- Filter / formula / select / output nodes take exactly one input with
  target_handle "in".
- Do not invent columns that are not in the dataset schemas.
- Output JSON only. No prose, no markdown fences.
"""


class AIPipelineError(ValueError):
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


async def _columns_for(session: AsyncSession, dataset_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[DatasetColumn]]:
    if not dataset_ids:
        return {}
    rows_q = await session.execute(select(DatasetColumn).where(DatasetColumn.dataset_id.in_(dataset_ids)))
    out: dict[uuid.UUID, list[DatasetColumn]] = {}
    for c in rows_q.scalars().all():
        out.setdefault(c.dataset_id, []).append(c)
    return out


def _allowlist_summary(datasets: list[Dataset], columns_by_id: dict[uuid.UUID, list[DatasetColumn]]) -> list[dict]:
    return [
        {
            "dataset_id": str(d.id),
            "name": d.name,
            "schema": d.schema_name,
            "table": d.table_name,
            "columns": [{"name": c.name, "type": c.data_type} for c in columns_by_id.get(d.id, [])],
        }
        for d in datasets
    ]


def _parse(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AIPipelineError(f"AI did not return valid JSON: {e}") from e


async def generate_pipeline_graph(
    *,
    session: AsyncSession,
    user: User,
    prompt: str,
    provider: str,
    model: str | None,
    dataset_ids: list[uuid.UUID] | None,
) -> dict[str, Any]:
    permitted = await _permitted_datasets_for_ai(session, user, provider, dataset_ids)
    if not permitted:
        raise AIPipelineError("no datasets permitted for AI use")
    cols = await _columns_for(session, [d.id for d in permitted])

    user_msg = (
        "Permitted datasets (use only these dataset_ids in source nodes):\n"
        + json.dumps(_allowlist_summary(permitted, cols), indent=2)
        + f"\n\nUser request: {prompt}\n\nReturn JSON now."
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

    parsed = _parse(result["text"])
    if not isinstance(parsed, dict):
        raise AIPipelineError("AI response is not an object")
    nodes = parsed.get("nodes") or []
    edges = parsed.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise AIPipelineError("AI response missing nodes or edges arrays")

    # Validate by running the compiler against the same dataset bundle.
    columns_by_id = {d.id: cols.get(d.id, []) for d in permitted}
    try:
        compile_pipeline(
            nodes=nodes,
            edges=edges,
            datasets=permitted,
            dataset_columns_by_id=columns_by_id,
        )
    except PipelineCompileError as e:
        raise AIPipelineError(f"AI returned invalid graph: {e}") from e

    return {
        "name": str(parsed.get("name") or "Untitled pipeline"),
        "description": parsed.get("description"),
        "nodes": nodes,
        "edges": edges,
    }
