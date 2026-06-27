import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.code_repo.models import CodeRepository
from app.deps import CurrentUserDep, SessionDep
from app.code_repo import git_service
from app.jobs import service as jobs_service
from app.notebooks.sandbox import validate_requirements_allowlist
from app.permissions.enforcement import effective_capabilities_for_object
from app.platform.service import upsert_resource

router = APIRouter(prefix="/code-repo", tags=["code-repo"])

DEMO_REPO_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def _require_repo_cap(
    session, user, repo_id: uuid.UUID, capability: str
) -> CodeRepository:
    """Load a repository and enforce a central ResourceACL capability.

    Mirrors the dataset/ML pattern: owner (or unowned/demo repos) always pass;
    otherwise the capability (or "manage") must be granted via the resource graph.
    """
    repo = await session.get(CodeRepository, repo_id)
    if repo is None:
        try:
            repo = await git_service.get_or_create_repo(session, repo_id)
            await session.commit()
        except Exception:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "repository not found")
    # Shared demo repo and legacy unowned repos remain open to all authenticated users.
    if repo.id == DEMO_REPO_ID or repo.owner_id in (None, user.id):
        return repo
    caps = await effective_capabilities_for_object(session, user, "code_repository", repo_id)
    if not ({capability, "manage"} & caps):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing capability: {capability}")
    return repo


async def _require_pr_repo_cap(session, user, pr, capability: str) -> None:
    """Authorize a PR operation against its owning repository."""
    await _require_repo_cap(session, user, pr.repo_id, capability)


# ---------------------------------------------------------------------------
# Transform execution
# ---------------------------------------------------------------------------

class CodeRunIn(BaseModel):
    files: dict[str, str]
    requirements: list[str] = []


class CodeTestIn(BaseModel):
    files: dict[str, str]
    test_file: str


class RepositoryCreateIn(BaseModel):
    name: str
    description: str | None = None
    repo_type: str = "python_transforms"
    workspace_parent_id: uuid.UUID | None = None


class RepositoryOut(BaseModel):
    id: str
    name: str
    description: str | None
    repo_type: str
    default_branch: str
    owner_id: str | None
    created_at: datetime
    updated_at: datetime


class RepositoryFileOut(BaseModel):
    path: str
    size: int
    language: str


class RepositoryFileContent(BaseModel):
    path: str
    content: str


class RepositoryFileWriteIn(BaseModel):
    path: str
    content: str


class RepositoryFolderCreateIn(BaseModel):
    path: str


def _repo_out(repo: CodeRepository) -> RepositoryOut:
    return RepositoryOut(
        id=str(repo.id),
        name=repo.name,
        description=repo.description,
        repo_type=repo.repo_type or "python_transforms",
        default_branch=repo.default_branch or "main",
        owner_id=str(repo.owner_id) if repo.owner_id else None,
        created_at=repo.created_at,
        updated_at=repo.updated_at,
    )


@router.get("/repositories", response_model=list[RepositoryOut])
async def list_repositories(session: SessionDep, user: CurrentUserDep) -> list[RepositoryOut]:
    all_repos = await git_service.list_repositories(session)
    visible: list[CodeRepository] = []
    for r in all_repos:
        if r.id == DEMO_REPO_ID or r.owner_id in (None, user.id):
            visible.append(r)
            continue
        caps = await effective_capabilities_for_object(session, user, "code_repository", r.id)
        if {"view_metadata", "manage"} & caps:
            visible.append(r)
    if not any(r.id == DEMO_REPO_ID for r in visible):
        visible.insert(0, await git_service.get_or_create_repo(session, DEMO_REPO_ID))
        await session.commit()
    return [_repo_out(r) for r in visible]


@router.post("/repositories", response_model=RepositoryOut)
async def create_repository(
    payload: RepositoryCreateIn, session: SessionDep, user: CurrentUserDep
) -> RepositoryOut:
    repo = await git_service.create_repository(
        session,
        name=payload.name,
        description=payload.description,
        owner_id=user.id,
        repo_type=payload.repo_type,
    )
    await upsert_resource(
        session,
        resource_type="code_repository",
        object_id=repo.id,
        name=repo.name,
        owner_user_id=user.id,
        metadata={"repo_type": repo.repo_type},
    )
    from app.workspace.service import create_linked_item
    await create_linked_item(
        session,
        user_id=user.id,
        name=repo.name,
        item_type="code_repository",
        resource_type="code_repository",
        resource_id=repo.id,
        parent_id=payload.workspace_parent_id,
    )
    await session.commit()
    return _repo_out(repo)


@router.get("/repositories/{repo_id}", response_model=RepositoryOut)
async def get_repository(repo_id: uuid.UUID, session: SessionDep, user: CurrentUserDep) -> RepositoryOut:
    repo = await _require_repo_cap(session, user, repo_id, "view_metadata")
    return _repo_out(repo)


@router.get("/repositories/{repo_id}/files", response_model=list[RepositoryFileOut])
async def list_repository_files(
    repo_id: uuid.UUID, session: SessionDep, user: CurrentUserDep
) -> list[RepositoryFileOut]:
    await _require_repo_cap(session, user, repo_id, "view_metadata")
    try:
        return [RepositoryFileOut(**f) for f in await git_service.list_files(session, repo_id)]
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/repositories/{repo_id}/files/content", response_model=RepositoryFileContent)
async def get_repository_file_content(
    repo_id: uuid.UUID,
    path: str,
    session: SessionDep,
    user: CurrentUserDep,
) -> RepositoryFileContent:
    await _require_repo_cap(session, user, repo_id, "view_metadata")
    try:
        return RepositoryFileContent(**await git_service.read_file(session, repo_id, path))
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.put("/repositories/{repo_id}/files/content")
async def put_repository_file_content(
    repo_id: uuid.UUID,
    payload: RepositoryFileWriteIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    await _require_repo_cap(session, user, repo_id, "edit")
    try:
        result = await git_service.write_file(session, repo_id, payload.path, payload.content)
        await session.commit()
        return result
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.post("/repositories/{repo_id}/folders")
async def create_repository_folder(
    repo_id: uuid.UUID,
    payload: RepositoryFolderCreateIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    await _require_repo_cap(session, user, repo_id, "edit")
    try:
        result = await git_service.create_folder(session, repo_id, payload.path)
        await session.commit()
        return result
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.post("/run")
async def run_transform_code(
    payload: CodeRunIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    try:
        validate_requirements_allowlist(payload.requirements)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    # User code never runs in this process. Enqueue a worker job that executes
    # the transform inside the locked-down Docker sandbox; the client polls
    # /jobs/{job_id} for the result.
    job = await jobs_service.enqueue(
        session, user=user, job_type="code_transform",
        input={
            "files": payload.files,
            "requirements": payload.requirements,
            "user_id": str(user.id),
        },
        resource_type="code_repository",
    )
    await session.commit()
    return {"job_id": str(job.id)}


@router.post("/test")
async def run_tests(
    payload: CodeTestIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    job = await jobs_service.enqueue(
        session, user=user, job_type="code_test",
        input={
            "files": payload.files,
            "test_file": payload.test_file,
            "user_id": str(user.id),
        },
        resource_type="code_repository",
    )
    await session.commit()
    return {"job_id": str(job.id)}


# ---------------------------------------------------------------------------
# Git endpoints
# ---------------------------------------------------------------------------

class GitCommitIn(BaseModel):
    files: dict[str, str]
    message: str


class GitBranchIn(BaseModel):
    branch_name: str
    from_branch: str = "main"


class PRCreateIn(BaseModel):
    title: str
    source_branch: str
    target_branch: str = "main"
    description: str | None = None


class PRCommentIn(BaseModel):
    body: str
    file: str | None = None
    line: int | None = None


class PRStatusIn(BaseModel):
    status: str  # approved | merged | closed


def _pr_out(pr: Any) -> dict:
    return {
        "id": str(pr.id),
        "repo_id": str(pr.repo_id),
        "title": pr.title,
        "description": pr.description,
        "source_branch": pr.source_branch,
        "target_branch": pr.target_branch,
        "status": pr.status,
        "author_id": str(pr.author_id) if pr.author_id else None,
        "comments": pr.comments or [],
        "created_at": pr.created_at.isoformat() if pr.created_at else None,
        "updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
        "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
    }


@router.get("/{repo_id}/git/log")
async def get_git_log(
    repo_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
    limit: int = 50,
) -> list[dict]:
    await _require_repo_cap(session, user, repo_id, "view_metadata")
    try:
        return await git_service.git_log(session, repo_id, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{repo_id}/git/commit")
async def create_git_commit(
    repo_id: uuid.UUID,
    payload: GitCommitIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    await _require_repo_cap(session, user, repo_id, "edit")
    try:
        result = await git_service.git_commit(
            session,
            repo_id,
            payload.files,
            payload.message,
            author_name=getattr(user, "name", None) or str(user.id),
            author_email=getattr(user, "email", None) or "noreply@mini-foundry.local",
        )
        await session.commit()
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{repo_id}/git/diff")
async def get_git_diff(
    repo_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    await _require_repo_cap(session, user, repo_id, "view_metadata")
    try:
        diff = await git_service.git_diff(session, repo_id)
        return {"diff": diff}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{repo_id}/git/branches")
async def list_git_branches(
    repo_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
) -> list[str]:
    await _require_repo_cap(session, user, repo_id, "view_metadata")
    try:
        return await git_service.git_list_branches(session, repo_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{repo_id}/git/branches")
async def create_git_branch(
    repo_id: uuid.UUID,
    payload: GitBranchIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    await _require_repo_cap(session, user, repo_id, "edit")
    try:
        result = await git_service.git_create_branch(
            session, repo_id, payload.branch_name, payload.from_branch
        )
        await session.commit()
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Pull requests
# ---------------------------------------------------------------------------

@router.get("/{repo_id}/pull-requests")
async def list_prs(
    repo_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
) -> list[dict]:
    await _require_repo_cap(session, user, repo_id, "view_metadata")
    prs = await git_service.list_pull_requests(session, repo_id)
    return [_pr_out(p) for p in prs]


@router.post("/{repo_id}/pull-requests")
async def create_pr(
    repo_id: uuid.UUID,
    payload: PRCreateIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    await _require_repo_cap(session, user, repo_id, "edit")
    pr = await git_service.create_pull_request(
        session,
        repo_id,
        payload.title,
        payload.source_branch,
        payload.target_branch,
        payload.description,
        user.id,
    )
    await session.commit()
    return _pr_out(pr)


@router.get("/pull-requests/{pr_id}")
async def get_pr(
    pr_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    pr = await git_service.get_pull_request(session, pr_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="PR not found")
    await _require_pr_repo_cap(session, user, pr, "view_metadata")
    return _pr_out(pr)


@router.get("/pull-requests/{pr_id}/diff")
async def get_pr_diff(
    pr_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    pr = await git_service.get_pull_request(session, pr_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="PR not found")
    await _require_pr_repo_cap(session, user, pr, "view_metadata")
    diff = await git_service.pr_diff(session, pr)
    return {"diff": diff}


@router.post("/pull-requests/{pr_id}/comments")
async def add_pr_comment(
    pr_id: uuid.UUID,
    payload: PRCommentIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    pr = await git_service.get_pull_request(session, pr_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="PR not found")
    await _require_pr_repo_cap(session, user, pr, "edit")
    author_name = getattr(user, "name", None) or str(user.id)
    pr = await git_service.add_pr_comment(
        session, pr, payload.body, author_name, payload.file, payload.line
    )
    await session.commit()
    return _pr_out(pr)


@router.patch("/pull-requests/{pr_id}/status")
async def update_pr_status(
    pr_id: uuid.UUID,
    payload: PRStatusIn,
    session: SessionDep,
    user: CurrentUserDep,
) -> dict:
    if payload.status not in ("approved", "merged", "closed"):
        raise HTTPException(status_code=400, detail="Invalid status")
    pr = await git_service.get_pull_request(session, pr_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="PR not found")
    await _require_pr_repo_cap(session, user, pr, "edit")
    pr = await git_service.update_pr_status(session, pr, payload.status)
    await session.commit()
    return _pr_out(pr)
