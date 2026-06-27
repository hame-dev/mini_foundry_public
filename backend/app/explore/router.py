"""GET /explore — unified search over datasets, ontology objects,
pipelines, and saved queries.

Each result is a normalized record:
    { id, kind, name, subtitle, ai_policy, updated_at, href,
      owner_id, lineage_in: [], lineage_out: [] }

Dataset visibility uses the same allowlist as the catalog; pipelines are
owner-scoped; ontology objects and saved queries are global read for any
authenticated user (matches the existing catalog/ontology routes).
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.dashboards.models import SavedQuery
from app.collaboration.models import ResourceComment
from app.data.catalog import list_visible_datasets
from app.data.models import DatasetColumn
from app.deps import CurrentUserDep, SessionDep
from app.ontology.models import OntologyObject
from app.permissions.enforcement import effective_resource_capabilities
from app.pipelines.models import Pipeline
from app.platform.models import Resource


router = APIRouter(prefix="/explore", tags=["explore"])

Kind = Literal["dataset", "pipeline", "object", "saved_query", "column", "resource", "comment"]
KINDS: tuple[Kind, ...] = ("dataset", "pipeline", "object", "saved_query", "column", "resource", "comment")


def _match(text: str | None, q: str) -> bool:
    if not q:
        return True
    if not text:
        return False
    return q.lower() in text.lower()


def _score(q: str, *fields: str | None) -> int:
    if not q:
        return 1
    needle = q.lower()
    score = 0
    for idx, field in enumerate(fields):
        if not field:
            continue
        value = str(field).lower()
        if value == needle:
            score += 100 - idx
        elif value.startswith(needle):
            score += 50 - idx
        elif needle in value:
            score += 20 - idx
    return max(score, 0)


@router.get("")
async def explore(
    session: SessionDep,
    user: CurrentUserDep,
    q: str = "",
    kinds: str | None = Query(default=None, description="comma-separated subset of dataset,pipeline,object,saved_query,column,resource,comment"),
    policy: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    selected: set[str] = set(KINDS) if not kinds else {k for k in kinds.split(",") if k in KINDS}
    results: list[dict[str, Any]] = []

    if "dataset" in selected:
        datasets = await list_visible_datasets(session, user.id)
        for d in datasets:
            if policy and d.ai_policy != policy:
                continue
            subtitle = f"{d.schema_name}.{d.table_name}"
            if d.row_count is not None:
                subtitle += f" · {d.row_count:,} rows"
            score = _score(q, d.name, d.description, subtitle)
            if not score:
                continue
            results.append(
                {
                    "id": str(d.id),
                    "kind": "dataset",
                    "name": d.name,
                    "subtitle": subtitle,
                    "description": d.description,
                    "ai_policy": d.ai_policy,
                    "owner_id": str(d.owner_id) if d.owner_id else None,
                    "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                    "href": f"/catalog/{d.id}",
                    "score": score,
                }
            )
            if "column" in selected and q:
                cols = (
                    await session.execute(select(DatasetColumn).where(DatasetColumn.dataset_id == d.id))
                ).scalars().all()
                for col in cols:
                    col_score = _score(q, col.name, col.description, col.data_type)
                    if not col_score:
                        continue
                    results.append(
                        {
                            "id": str(col.id),
                            "kind": "column",
                            "name": f"{d.name}.{col.name}",
                            "subtitle": col.data_type or "Dataset column",
                            "description": col.description,
                            "ai_policy": d.ai_policy,
                            "owner_id": str(d.owner_id) if d.owner_id else None,
                            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                            "href": f"/catalog/{d.id}",
                            "dataset_id": str(d.id),
                            "score": col_score,
                        }
                    )

    if "pipeline" in selected:
        p_q = await session.execute(
            select(Pipeline).where(Pipeline.owner_id == user.id).order_by(Pipeline.updated_at.desc())
        )
        for p in p_q.scalars().all():
            if policy and p.ai_policy != policy:
                continue
            subtitle = "Pipeline · " + (p.last_run_status or "draft")
            score = _score(q, p.name, p.description, p.last_run_status)
            if not score:
                continue
            results.append(
                {
                    "id": str(p.id),
                    "kind": "pipeline",
                    "name": p.name,
                    "subtitle": subtitle,
                    "description": p.description,
                    "ai_policy": p.ai_policy,
                    "owner_id": str(p.owner_id) if p.owner_id else None,
                    "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                    "href": f"/pipelines/{p.id}",
                    "output_dataset_id": str(p.output_dataset_id) if p.output_dataset_id else None,
                    "score": score,
                }
            )

    if "object" in selected:
        o_q = await session.execute(select(OntologyObject))
        for o in o_q.scalars().all():
            subtitle = f"Ontology · {o.primary_key}"
            prop_text = " ".join(str((p or {}).get("name") or (p or {}).get("column") or "") for p in (o.properties or []))
            score = _score(q, o.type_name, o.description, o.primary_key, prop_text)
            if not score:
                continue
            results.append(
                {
                    "id": str(o.id),
                    "kind": "object",
                    "name": o.type_name,
                    "subtitle": subtitle,
                    "description": o.description,
                    "ai_policy": None,
                    "owner_id": None,
                    "updated_at": o.updated_at.isoformat() if o.updated_at else None,
                    "href": f"/admin/ontology?type={o.type_name}",
                    "dataset_id": str(o.dataset_id),
                    "score": score,
                }
            )

    if "saved_query" in selected:
        sq_q = await session.execute(
            select(SavedQuery).where(SavedQuery.owner_id == user.id).order_by(SavedQuery.created_at.desc())
        )
        for sq in sq_q.scalars().all():
            score = _score(q, sq.name, sq.sql)
            if not score:
                continue
            results.append(
                {
                    "id": str(sq.id),
                    "kind": "saved_query",
                    "name": sq.name,
                    "subtitle": "Saved query",
                    "description": None,
                    "ai_policy": None,
                    "owner_id": str(sq.owner_id) if sq.owner_id else None,
                    "updated_at": sq.created_at.isoformat() if sq.created_at else None,
                    "href": "/sql",
                    "score": score,
                }
            )

    if "resource" in selected:
        rows = (
            await session.execute(
                select(Resource).where(Resource.deleted_at.is_(None)).order_by(Resource.updated_at.desc()).limit(max(limit, 200))
            )
        ).scalars().all()
        for resource in rows:
            caps = await effective_resource_capabilities(session, user, resource)
            if not ({"view_metadata", "view_data", "manage"} & set(caps) or resource.owner_user_id == user.id):
                continue
            score = _score(q, resource.name, resource.resource_type)
            if not score:
                continue
            results.append(
                {
                    "id": str(resource.id),
                    "kind": "resource",
                    "name": resource.name,
                    "subtitle": resource.resource_type,
                    "description": None,
                    "ai_policy": None,
                    "owner_id": str(resource.owner_user_id) if resource.owner_user_id else None,
                    "updated_at": resource.updated_at.isoformat() if resource.updated_at else None,
                    "href": f"/workspace/resources?resource_id={resource.id}",
                    "score": score,
                }
            )

    if "comment" in selected:
        comments = (
            await session.execute(
                select(ResourceComment, Resource)
                .join(Resource, Resource.id == ResourceComment.resource_id)
                .where(Resource.deleted_at.is_(None))
                .order_by(ResourceComment.created_at.desc())
                .limit(max(limit, 200))
            )
        ).all()
        for comment, resource in comments:
            caps = await effective_resource_capabilities(session, user, resource)
            if not ({"view_metadata", "view_data", "manage"} & set(caps) or resource.owner_user_id == user.id):
                continue
            score = _score(q, comment.body, resource.name, resource.resource_type)
            if not score:
                continue
            results.append(
                {
                    "id": str(comment.id),
                    "kind": "comment",
                    "name": f"Comment on {resource.name}",
                    "subtitle": resource.resource_type,
                    "description": comment.body,
                    "ai_policy": None,
                    "owner_id": str(comment.author_id) if comment.author_id else None,
                    "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
                    "href": f"/workspace/resources?resource_id={resource.id}&comment_id={comment.id}",
                    "score": score,
                }
            )

    results.sort(key=lambda r: (int(r.get("score") or 0), r.get("updated_at") or ""), reverse=True)
    return {"results": results[:limit], "total": len(results)}
