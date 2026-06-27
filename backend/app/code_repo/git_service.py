"""Git service: manages per-repository bare Git repos using GitPython.

Each CodeRepository has a ``git_path`` pointing to a bare Git repo directory
(e.g. ``/var/mf_repos/<repo_id>.git``).  The service creates that directory on
first use and exposes log/commit/diff/branch/PR operations.
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.code_repo.models import CodeRepository, PullRequest

_REPO_BASE = os.environ.get("MF_GIT_REPO_BASE", "/tmp/mf_repos")
_DEMO_REPO_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _repo_path(repo_id: uuid.UUID) -> str:
    return os.path.join(_REPO_BASE, f"{repo_id}.git")


def _ensure_git() -> None:
    try:
        import git  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "GitPython or the git executable is not available. "
            "Install backend requirements and rebuild the backend image."
        ) from exc


def _open_or_init(path: str):
    """Return an initialized git.Repo object (non-bare, working tree = path)."""
    import git

    # Non-bare repos keep git metadata in <path>/.git
    if os.path.exists(os.path.join(path, ".git")):
        return git.Repo(path)

    Path(path).mkdir(parents=True, exist_ok=True)
    try:
        repo = git.Repo.init(path, initial_branch="main")
    except TypeError:
        repo = git.Repo.init(path)
        try:
            repo.git.branch("-M", "main")
        except git.GitCommandError:
            pass
    # Create an initial empty commit so we always have a HEAD reference
    repo.index.commit("Initial commit")
    return repo


def _starter_files(name: str) -> dict[str, str]:
    """The scaffold written into a fresh python_transforms repository."""
    return {
        "README.md": f"# {name}\n\nPython transform repository for Mini Foundry.\n",
        "src/transform.py": (
            "import pandas as pd\n\n"
            "from platform_sdk import transform, Input, Output\n\n\n"
            "@transform(output=Output(\"Demo Transform Output\"))\n"
            "def build_summary():\n"
            "    \"\"\"Starter @transform.\n\n"
            "    It takes no inputs so the repository builds out of the box. To\n"
            "    read an existing dataset, declare it as an Input and add a\n"
            "    matching parameter, e.g.::\n\n"
            "        @transform(\n"
            "            customers=Input(\"customers\"),\n"
            "            output=Output(\"Demo Transform Output\"),\n"
            "        )\n"
            "        def build_summary(customers):\n"
            "            return customers.head(10)\n"
            "    \"\"\"\n"
            "    return pd.DataFrame(\n"
            "        [\n"
            "            {\"metric\": \"alpha\", \"value\": 1},\n"
            "            {\"metric\": \"beta\", \"value\": 2},\n"
            "        ]\n"
            "    )\n"
        ),
        "tests/test_transform.py": (
            "from src.transform import build_summary\n\n\n"
            "def test_build_summary_has_rows():\n"
            "    df = build_summary()\n"
            "    assert len(df) == 2\n"
            "    assert list(df.columns) == [\"metric\", \"value\"]\n"
        ),
    }


# Scaffold files that refresh_starter_files() will overwrite in place. README
# is intentionally excluded so user edits to it are preserved.
_REFRESHABLE_STARTER_FILES = ("src/transform.py", "tests/test_transform.py")


def _write_starter_files(repo, path: str, name: str) -> None:
    root = Path(path)
    files = _starter_files(name)
    for rel, content in files.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_text(content, encoding="utf-8")
            repo.index.add([rel])
    if repo.is_dirty(untracked_files=True):
        repo.index.commit("Add starter repository scaffold")


async def refresh_starter_files(
    session: AsyncSession,
    repo_id: uuid.UUID,
    *,
    paths: tuple[str, ...] = _REFRESHABLE_STARTER_FILES,
) -> list[str]:
    """Overwrite an existing repo's scaffold files with the current starter
    content and commit. Returns the relative paths that actually changed.

    Used to migrate already-created repositories (e.g. the demo repo) onto an
    updated scaffold; files whose content already matches are left untouched.
    """
    import git

    cr = await get_or_create_repo(session, repo_id)
    repo = git.Repo(cr.git_path)
    root = Path(cr.git_path)
    files = _starter_files(cr.name)
    changed: list[str] = []
    for rel in paths:
        content = files.get(rel)
        if content is None:
            continue
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.read_text(encoding="utf-8") == content:
            continue
        dest.write_text(content, encoding="utf-8")
        repo.index.add([rel])
        changed.append(rel)
    if changed:
        repo.index.commit("Refresh starter repository scaffold")
    return changed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_or_create_repo(
    session: AsyncSession, repo_id: uuid.UUID
) -> "CodeRepository":
    _ensure_git()
    q = await session.execute(select(CodeRepository).where(CodeRepository.id == repo_id))
    cr = q.scalar_one_or_none()
    if cr is None:
        if repo_id != _DEMO_REPO_ID:
            raise ValueError(f"CodeRepository {repo_id} not found")
        cr = CodeRepository(
            id=repo_id,
            name="Demo Code Repository",
            description="Default browser workspace repository",
        )
        session.add(cr)
        await session.flush()

    if not cr.git_path:
        path = _repo_path(repo_id)
        repo = _open_or_init(path)
        _write_starter_files(repo, path, cr.name)
        cr.git_path = path
        await session.flush()

    return cr


async def create_repository(
    session: AsyncSession,
    *,
    name: str,
    description: str | None,
    owner_id: uuid.UUID | None,
    repo_type: str = "python_transforms",
) -> CodeRepository:
    _ensure_git()
    cr = CodeRepository(
        name=name,
        description=description,
        owner_id=owner_id,
        repo_type=repo_type,
        default_branch="main",
    )
    session.add(cr)
    await session.flush()
    path = _repo_path(cr.id)
    repo = _open_or_init(path)
    if repo_type == "python_transforms":
        _write_starter_files(repo, path, name)
    cr.git_path = path
    await session.flush()
    return cr


def _safe_worktree_path(worktree: str, file_path: str) -> Path:
    candidate = (Path(worktree) / file_path).resolve()
    root = Path(worktree).resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("file path escapes repository")
    if ".git" in candidate.relative_to(root).parts:
        raise ValueError("git internals are not editable")
    return candidate


async def list_repositories(session: AsyncSession, owner_id: uuid.UUID | None = None) -> list[CodeRepository]:
    stmt = select(CodeRepository).order_by(CodeRepository.updated_at.desc())
    if owner_id is not None:
        stmt = stmt.where((CodeRepository.owner_id == owner_id) | (CodeRepository.id == _DEMO_REPO_ID))
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def list_files(session: AsyncSession, repo_id: uuid.UUID) -> list[dict[str, Any]]:
    cr = await get_or_create_repo(session, repo_id)
    root = Path(cr.git_path)
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        files.append({"path": rel, "size": path.stat().st_size, "language": rel.rsplit(".", 1)[-1] if "." in rel else "text"})
    return files


async def read_file(session: AsyncSession, repo_id: uuid.UUID, file_path: str) -> dict[str, Any]:
    cr = await get_or_create_repo(session, repo_id)
    path = _safe_worktree_path(cr.git_path, file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(file_path)
    return {"path": file_path, "content": path.read_text(encoding="utf-8")}


async def write_file(
    session: AsyncSession,
    repo_id: uuid.UUID,
    file_path: str,
    content: str,
) -> dict[str, Any]:
    cr = await get_or_create_repo(session, repo_id)
    path = _safe_worktree_path(cr.git_path, file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    cr.updated_at = datetime.utcnow()
    await session.flush()
    return {"path": file_path, "bytes": len(content.encode("utf-8"))}


async def create_folder(session: AsyncSession, repo_id: uuid.UUID, folder_path: str) -> dict[str, Any]:
    clean = folder_path.strip().strip("/")
    if not clean:
        raise ValueError("folder path required")
    return await write_file(session, repo_id, f"{clean}/.gitkeep", "")


async def git_log(
    session: AsyncSession, repo_id: uuid.UUID, limit: int = 50
) -> list[dict[str, Any]]:
    cr = await get_or_create_repo(session, repo_id)
    import git

    repo = git.Repo(cr.git_path)
    commits = []
    try:
        for c in repo.iter_commits(max_count=limit):
            commits.append(
                {
                    "sha": c.hexsha,
                    "short_sha": c.hexsha[:7],
                    "message": c.message.strip(),
                    "author": c.author.name,
                    "email": c.author.email,
                    "committed_at": datetime.fromtimestamp(c.committed_date).isoformat(),
                }
            )
    except git.GitCommandError:
        pass  # empty repo has no commits beyond the initial one
    return commits


async def git_commit(
    session: AsyncSession,
    repo_id: uuid.UUID,
    files: dict[str, str],
    message: str,
    author_name: str = "Mini Foundry",
    author_email: str = "noreply@mini-foundry.local",
) -> dict[str, Any]:
    cr = await get_or_create_repo(session, repo_id)
    import git

    repo = git.Repo(cr.git_path)
    worktree = cr.git_path  # non-bare repo; work tree == repo dir

    # Write files into the working tree
    for filename, content in files.items():
        dest = os.path.join(worktree, filename)
        os.makedirs(os.path.dirname(dest), exist_ok=True) if os.sep in filename else None
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)
        repo.index.add([filename])

    actor = git.Actor(author_name, author_email)
    commit = repo.index.commit(message, author=actor, committer=actor)
    return {"sha": commit.hexsha, "message": message}


async def git_diff(
    session: AsyncSession, repo_id: uuid.UUID
) -> str:
    cr = await get_or_create_repo(session, repo_id)
    import git

    repo = git.Repo(cr.git_path)
    return repo.git.diff()


async def git_create_branch(
    session: AsyncSession, repo_id: uuid.UUID, branch_name: str, from_branch: str = "main"
) -> dict[str, Any]:
    cr = await get_or_create_repo(session, repo_id)
    import git

    repo = git.Repo(cr.git_path)
    # Checkout source branch first
    try:
        repo.git.checkout(from_branch)
    except git.GitCommandError:
        pass  # might already be there

    new_branch = repo.create_head(branch_name)
    new_branch.checkout()
    return {"branch": branch_name, "from": from_branch}


async def git_list_branches(
    session: AsyncSession, repo_id: uuid.UUID
) -> list[str]:
    cr = await get_or_create_repo(session, repo_id)
    import git

    repo = git.Repo(cr.git_path)
    return [b.name for b in repo.heads]


# ---------------------------------------------------------------------------
# Pull requests (stored in DB)
# ---------------------------------------------------------------------------


async def create_pull_request(
    session: AsyncSession,
    repo_id: uuid.UUID,
    title: str,
    source_branch: str,
    target_branch: str = "main",
    description: str | None = None,
    author_id: uuid.UUID | None = None,
) -> PullRequest:
    pr = PullRequest(
        repo_id=repo_id,
        title=title,
        description=description,
        source_branch=source_branch,
        target_branch=target_branch,
        author_id=author_id,
    )
    session.add(pr)
    await session.flush()
    return pr


async def list_pull_requests(
    session: AsyncSession, repo_id: uuid.UUID
) -> list[PullRequest]:
    q = await session.execute(
        select(PullRequest)
        .where(PullRequest.repo_id == repo_id)
        .order_by(PullRequest.created_at.desc())
    )
    return list(q.scalars().all())


async def get_pull_request(
    session: AsyncSession, pr_id: uuid.UUID
) -> PullRequest | None:
    q = await session.execute(select(PullRequest).where(PullRequest.id == pr_id))
    return q.scalar_one_or_none()


async def pr_diff(
    session: AsyncSession, pr: PullRequest
) -> str:
    """Return the unified diff between source and target branches."""
    cr_q = await session.execute(
        select(CodeRepository).where(CodeRepository.id == pr.repo_id)
    )
    cr = cr_q.scalar_one_or_none()
    if cr is None or not cr.git_path:
        return ""
    import git

    repo = git.Repo(cr.git_path)
    try:
        return repo.git.diff(pr.target_branch, pr.source_branch)
    except git.GitCommandError:
        return ""


async def add_pr_comment(
    session: AsyncSession,
    pr: PullRequest,
    body: str,
    author_name: str,
    file: str | None = None,
    line: int | None = None,
) -> PullRequest:
    comments = list(pr.comments or [])
    comments.append(
        {
            "id": str(uuid.uuid4()),
            "body": body,
            "author": author_name,
            "file": file,
            "line": line,
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    pr.comments = comments
    pr.updated_at = datetime.utcnow()
    await session.flush()
    return pr


async def update_pr_status(
    session: AsyncSession,
    pr: PullRequest,
    status: str,
) -> PullRequest:
    import git

    pr.status = status
    pr.updated_at = datetime.utcnow()
    if status == "merged":
        pr.merged_at = datetime.utcnow()
        # Attempt actual merge in git
        cr_q = await session.execute(
            select(CodeRepository).where(CodeRepository.id == pr.repo_id)
        )
        cr = cr_q.scalar_one_or_none()
        if cr and cr.git_path:
            repo = git.Repo(cr.git_path)
            try:
                repo.git.checkout(pr.target_branch)
                repo.git.merge(pr.source_branch, "--no-ff", "-m", f"Merge PR: {pr.title}")
            except git.GitCommandError:
                pass  # merge conflict — caller handles it
    await session.flush()
    return pr
