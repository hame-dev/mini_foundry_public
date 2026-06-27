import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.ai import gateway
from app.audit.logger import log_event
from app.deps import CurrentUserDep, SessionDep
from app.data.models import Dataset, DatasetColumn
from app.execution.sql_validator import SqlValidationError
from app.governed_query.service import governed_query
from app.jobs import service as jobs_service
from app.notebooks import ai_python, service
from app.notebooks.sandbox import validate_requirements_allowlist
from app.notebooks.models import CELL_TYPES, KIND_CELL_TYPES, NOTEBOOK_KINDS, Notebook, NotebookCell, NotebookPermission
from app.notebooks.permissions import effective_notebook_permission
from app.permissions.enforcement import (
    PermissionDenied,
    bump_permission_version,
    effective_capabilities_for_object,
    require_object_capability,
)
from app.platform.service import upsert_resource

router = APIRouter(prefix="/notebooks", tags=["notebooks"])


# ----- pydantic ----------------------------------------------------------


class NotebookSummary(BaseModel):
    id: str
    title: str
    description: str | None
    owner_id: str | None
    ai_policy: str
    notebook_kind: str = "python"
    requirements: list[str] | None = None
    kernel_name: str | None = None
    workspace_metadata: dict | None = None
    created_at: datetime
    updated_at: datetime


class CellOut(BaseModel):
    id: str
    notebook_id: str
    position: int
    cell_type: str
    source: str
    dataset_ids: list[str]
    last_output: dict | None
    last_run_at: datetime | None
    last_status: str | None
    last_job_id: str | None


class NotebookDetail(NotebookSummary):
    cells: list[CellOut]


class CreateNotebookIn(BaseModel):
    title: str
    description: str | None = None
    ai_policy: str = "local_only"
    notebook_kind: str = "python"
    requirements: list[str] | None = None
    kernel_name: str | None = None
    workspace_metadata: dict | None = None
    workspace_parent_id: uuid.UUID | None = None


class UpdateNotebookIn(BaseModel):
    title: str | None = None
    description: str | None = None
    ai_policy: str | None = None
    requirements: list[str] | None = None
    kernel_name: str | None = None
    workspace_metadata: dict | None = None


class CreateCellIn(BaseModel):
    cell_type: str
    source: str = ""
    dataset_ids: list[uuid.UUID] = []


class UpdateCellIn(BaseModel):
    source: str | None = None
    dataset_ids: list[uuid.UUID] | None = None


class ReorderIn(BaseModel):
    ordered_ids: list[uuid.UUID]


class RunCellIn(BaseModel):
    # ai_prompt-only knobs (ignored for other cell types)
    run_after_generate: bool = True
    provider: str = "ollama"
    model: str | None = None


# ----- helpers -----------------------------------------------------------


def _summary(n: Notebook) -> NotebookSummary:
    return NotebookSummary(
        id=str(n.id), title=n.title, description=n.description,
        owner_id=str(n.owner_id) if n.owner_id else None,
        ai_policy=n.ai_policy, notebook_kind=n.notebook_kind,
        requirements=n.requirements,
        kernel_name=n.kernel_name,
        workspace_metadata=n.workspace_metadata,
        created_at=n.created_at, updated_at=n.updated_at,
    )


def _cell_out(c: NotebookCell) -> CellOut:
    return CellOut(
        id=str(c.id), notebook_id=str(c.notebook_id), position=c.position,
        cell_type=c.cell_type, source=c.source,
        dataset_ids=[str(x) for x in (c.dataset_ids or [])],
        last_output=c.last_output, last_run_at=c.last_run_at,
        last_status=c.last_status,
        last_job_id=str(c.last_job_id) if c.last_job_id else None,
    )


# Central ResourceACL is the authority; legacy NotebookPermission remains a
# compatibility fallback until those rows are fully migrated/backfilled.
async def _can_view(session, user, nb: Notebook) -> bool:
    if nb.owner_id == user.id:
        return True
    caps = await effective_capabilities_for_object(session, user, "notebook", nb.id)
    if {"view_metadata", "manage"} & caps:
        return True
    eff = await effective_notebook_permission(session, user.id, nb.id)
    return eff.can_view


async def _can_edit(session, user, nb: Notebook) -> bool:
    if nb.owner_id == user.id:
        return True
    caps = await effective_capabilities_for_object(session, user, "notebook", nb.id)
    if {"edit", "manage"} & caps:
        return True
    eff = await effective_notebook_permission(session, user.id, nb.id)
    return eff.can_edit


async def _can_run(session, user, nb: Notebook) -> bool:
    if nb.owner_id == user.id:
        return True
    caps = await effective_capabilities_for_object(session, user, "notebook", nb.id)
    if {"run", "edit", "manage"} & caps:
        return True
    eff = await effective_notebook_permission(session, user.id, nb.id)
    return eff.can_run or eff.can_edit


async def _can_manage(session, user, nb: Notebook) -> bool:
    if nb.owner_id == user.id:
        return True
    caps = await effective_capabilities_for_object(session, user, "notebook", nb.id)
    if "manage" in caps:
        return True
    eff = await effective_notebook_permission(session, user.id, nb.id)
    return eff.can_manage


# ----- CRUD --------------------------------------------------------------


@router.get("", response_model=list[NotebookSummary])
async def list_notebooks(session: SessionDep, user: CurrentUserDep) -> list[NotebookSummary]:
    rows = await service.list_visible_notebooks(session, user.id)
    return [_summary(r) for r in rows]


@router.post("", response_model=NotebookDetail)
async def create_notebook(
    payload: CreateNotebookIn, session: SessionDep, user: CurrentUserDep
) -> NotebookDetail:
    if payload.notebook_kind not in NOTEBOOK_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "notebook_kind must be sql|python")
    try:
        validate_requirements_allowlist(payload.requirements)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    nb = Notebook(
        title=payload.title, description=payload.description,
        ai_policy=payload.ai_policy, notebook_kind=payload.notebook_kind, owner_id=user.id,
        requirements=payload.requirements,
        kernel_name=payload.kernel_name or ("python3" if payload.notebook_kind == "python" else "sql"),
        workspace_metadata=payload.workspace_metadata or {},
    )
    session.add(nb)
    await session.flush()

    await upsert_resource(
        session,
        resource_type="notebook",
        object_id=nb.id,
        name=nb.title,
        owner_user_id=user.id,
        metadata={"kernel_name": nb.kernel_name, "notebook_kind": nb.notebook_kind},
    )
    # Legacy compatibility row (NotebookPermission); ResourceACL is authoritative.
    session.add(NotebookPermission(
        notebook_id=nb.id, subject_type="user", subject_id=user.id,
        can_view=True, can_edit=True, can_run=True, can_manage=True,
    ))
    await bump_permission_version(session)
    from app.workspace.service import create_linked_item
    await create_linked_item(
        session,
        user_id=user.id,
        name=nb.title,
        item_type="notebook",
        resource_type="notebook",
        resource_id=nb.id,
        parent_id=payload.workspace_parent_id,
    )
    await log_event(
        session, user=user, event_type="DASHBOARD_EDITED",  # reusing event for now
        resource_type="notebook", resource_id=str(nb.id),
        input_summary={"action": "create", "title": nb.title},
    )
    await session.commit()
    return NotebookDetail(**_summary(nb).model_dump(), cells=[])


@router.get("/{notebook_id}", response_model=NotebookDetail)
async def get_notebook(
    notebook_id: uuid.UUID, session: SessionDep, user: CurrentUserDep
) -> NotebookDetail:
    nb = await session.get(Notebook, notebook_id)
    if nb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notebook not found")
    if not await _can_view(session, user, nb):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no view permission")
    cells = await service.get_cells(session, notebook_id)
    return NotebookDetail(**_summary(nb).model_dump(), cells=[_cell_out(c) for c in cells])


@router.put("/{notebook_id}", response_model=NotebookSummary)
async def update_notebook(
    notebook_id: uuid.UUID, payload: UpdateNotebookIn,
    session: SessionDep, user: CurrentUserDep,
) -> NotebookSummary:
    nb = await session.get(Notebook, notebook_id)
    if nb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notebook not found")
    try:
        validate_requirements_allowlist(payload.requirements)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    if not await _can_edit(session, user, nb):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no edit permission")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(nb, field, value)
    nb.updated_at = datetime.utcnow()
    await session.commit()
    return _summary(nb)


@router.delete("/{notebook_id}")
async def delete_notebook(
    notebook_id: uuid.UUID, session: SessionDep, user: CurrentUserDep,
) -> dict:
    nb = await session.get(Notebook, notebook_id)
    if nb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notebook not found")
    if not await _can_manage(session, user, nb):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no manage permission")
    await session.delete(nb)
    await session.commit()
    return {"ok": True}


# ----- cells -------------------------------------------------------------


@router.post("/{notebook_id}/cells", response_model=CellOut)
async def add_cell(
    notebook_id: uuid.UUID, payload: CreateCellIn,
    session: SessionDep, user: CurrentUserDep,
) -> CellOut:
    nb = await session.get(Notebook, notebook_id)
    if nb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notebook not found")
    if not await _can_edit(session, user, nb):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no edit permission")
    if payload.cell_type not in CELL_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown cell_type: {payload.cell_type}")
    if payload.cell_type not in KIND_CELL_TYPES.get(nb.notebook_kind, set()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{nb.notebook_kind} notebook cannot contain {payload.cell_type} cells")
    cell = await service.add_cell(
        session, notebook_id=notebook_id, cell_type=payload.cell_type,
        source=payload.source, dataset_ids=payload.dataset_ids,
    )
    await session.commit()
    return _cell_out(cell)


@router.put("/{notebook_id}/cells/{cell_id}", response_model=CellOut)
async def update_cell(
    notebook_id: uuid.UUID, cell_id: uuid.UUID, payload: UpdateCellIn,
    session: SessionDep, user: CurrentUserDep,
) -> CellOut:
    nb = await session.get(Notebook, notebook_id)
    cell = await session.get(NotebookCell, cell_id)
    if nb is None or cell is None or cell.notebook_id != notebook_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cell not found")
    if not await _can_edit(session, user, nb):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no edit permission")
    if payload.source is not None:
        cell.source = payload.source
    if payload.dataset_ids is not None:
        cell.dataset_ids = list(payload.dataset_ids)
    await session.commit()
    return _cell_out(cell)


@router.delete("/{notebook_id}/cells/{cell_id}")
async def delete_cell(
    notebook_id: uuid.UUID, cell_id: uuid.UUID,
    session: SessionDep, user: CurrentUserDep,
) -> dict:
    nb = await session.get(Notebook, notebook_id)
    cell = await session.get(NotebookCell, cell_id)
    if nb is None or cell is None or cell.notebook_id != notebook_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cell not found")
    if not await _can_edit(session, user, nb):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no edit permission")
    await session.delete(cell)
    await session.commit()
    return {"ok": True}


@router.post("/{notebook_id}/reorder")
async def reorder(
    notebook_id: uuid.UUID, payload: ReorderIn,
    session: SessionDep, user: CurrentUserDep,
) -> dict:
    nb = await session.get(Notebook, notebook_id)
    if nb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notebook not found")
    if not await _can_edit(session, user, nb):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no edit permission")
    await service.reorder_cells(session, notebook_id, payload.ordered_ids)
    await session.commit()
    return {"ok": True}


# ----- run ---------------------------------------------------------------


async def _check_dataset_caps(
    session, user, dataset_ids: list[uuid.UUID], capability: str,
) -> None:
    for did in dataset_ids:
        ds = await session.get(Dataset, did)
        if ds is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"dataset {did} not found")
        try:
            await require_object_capability(session, user, "dataset", did, capability)
        except PermissionDenied as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"dataset {did}: {e}")


@router.post("/{notebook_id}/cells/{cell_id}/run")
async def run_cell(
    notebook_id: uuid.UUID, cell_id: uuid.UUID, payload: RunCellIn,
    session: SessionDep, user: CurrentUserDep,
) -> dict:
    nb = await session.get(Notebook, notebook_id)
    cell = await session.get(NotebookCell, cell_id)
    if nb is None or cell is None or cell.notebook_id != notebook_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cell not found")
    if not await _can_run(session, user, nb):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no run permission")
    if cell.last_status in {"queued", "running"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "cell already queued or running")

    cap = {"sql": "can_use_in_sql", "python": "can_use_in_python", "ai_prompt": "can_use_with_ai"}.get(cell.cell_type)
    if cap:
        await _check_dataset_caps(session, user, list(cell.dataset_ids or []), cap)

    # Markdown: no-op
    if cell.cell_type == "markdown":
        cell.last_output = {"markdown": cell.source}
        cell.last_status = "succeeded"
        cell.last_run_at = datetime.utcnow()
        await session.commit()
        return {"status": "succeeded", "output": cell.last_output}

    # SQL: synchronous via governed query service
    if cell.cell_type == "sql":
        try:
            result = await governed_query(
                session,
                user,
                cell.source,
                dataset_ids=list(cell.dataset_ids or []),
                capability="use_in_sql",
                audit_resource_type="notebook_cell",
                audit_resource_id=str(cell.id),
            )
        except SqlValidationError as e:
            cell.last_status = "failed"
            cell.last_output = {"error": str(e)}
            await session.commit()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        rows = result["rows"]
        cell.last_output = {"columns": result["columns"], "rows": rows}
        cell.last_status = "succeeded"
        cell.last_run_at = datetime.utcnow()
        await log_event(
            session, user=user, event_type="SQL_RUN",
            resource_type="notebook_cell", resource_id=str(cell.id),
            input_summary={"sql": cell.source}, output_summary={"row_count": len(rows)},
        )
        await session.commit()
        return {"status": "succeeded", "output": cell.last_output}

    # AI prompt: call gateway here (async), then optionally enqueue execution
    if cell.cell_type == "ai_prompt":
        datasets = []
        cols_by_id: dict[str, list[DatasetColumn]] = {}
        if cell.dataset_ids:
            ds_rows = (await session.execute(
                select(Dataset).where(Dataset.id.in_(cell.dataset_ids))
            )).scalars().all()
            datasets = list(ds_rows)
            for d in datasets:
                gateway.enforce_ai_policy(d, payload.provider)
            cols_q = await session.execute(
                select(DatasetColumn).where(DatasetColumn.dataset_id.in_(cell.dataset_ids))
            )
            for c in cols_q.scalars().all():
                cols_by_id.setdefault(str(c.dataset_id), []).append(c)

        messages = ai_python.build_messages(cell.source, datasets, cols_by_id)
        model = payload.model or gateway.default_model_for(payload.provider)
        try:
            result = await gateway.generate(
                session=session, provider=payload.provider, model=model,
                messages=messages, datasets=datasets, response_format="json",
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"AI provider error: {e}")
        parsed = ai_python.parse_response(result["text"])

        await log_event(
            session, user=user, event_type="AI_PROVIDER_USED",
            resource_type="notebook_cell", resource_id=str(cell.id),
            provider=payload.provider,
            input_summary={"prompt": cell.source, "model": model},
            output_summary={"explanation": parsed.get("explanation", "")},
        )

        if not payload.run_after_generate:
            # Don't execute. Just store the generated code so the user can review.
            cell.last_output = {"generated_code": parsed["python"], "explanation": parsed["explanation"]}
            cell.last_status = "succeeded"
            cell.last_run_at = datetime.utcnow()
            await session.commit()
            return {"status": "succeeded", "output": cell.last_output}

        # Auto-run: enqueue a notebook_cell job that will run the generated code.
        job = await jobs_service.enqueue(
            session, user=user, job_type="notebook_cell",
            input={
                "notebook_id": str(notebook_id),
                "cell_id": str(cell.id),
                "cell_type": "ai_prompt",
                "source_snapshot": parsed["python"],
                "explanation": parsed["explanation"],
                "dataset_ids": [str(x) for x in (cell.dataset_ids or [])],
                "user_id": str(user.id),
            },
            resource_type="notebook_cell", resource_id=str(cell.id),
        )
        cell.last_status = "queued"
        cell.last_job_id = job.id
        await log_event(
            session, user=user, event_type="PYTHON_EXECUTED",
            resource_type="notebook_cell", resource_id=str(cell.id),
            input_summary={"via": "ai_prompt", "job_id": str(job.id)},
        )
        await session.commit()
        return {"status": "queued", "job_id": str(job.id)}

    # Python: enqueue sandbox job
    if cell.cell_type == "python":
        job = await jobs_service.enqueue(
            session, user=user, job_type="notebook_cell",
            input={
                "notebook_id": str(notebook_id),
                "cell_id": str(cell.id),
                "cell_type": "python",
                "source_snapshot": cell.source,
                "dataset_ids": [str(x) for x in (cell.dataset_ids or [])],
                "user_id": str(user.id),
            },
            resource_type="notebook_cell", resource_id=str(cell.id),
        )
        cell.last_status = "queued"
        cell.last_job_id = job.id
        await log_event(
            session, user=user, event_type="PYTHON_EXECUTED",
            resource_type="notebook_cell", resource_id=str(cell.id),
            input_summary={"job_id": str(job.id)},
        )
        await session.commit()
        return {"status": "queued", "job_id": str(job.id)}

    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"cannot run cell_type {cell.cell_type}")
