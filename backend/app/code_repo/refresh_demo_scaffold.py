"""Refresh an existing repository's starter scaffold to the current version.

Already-created repos keep whatever scaffold they were seeded with, so they do
not pick up changes to ``_starter_files``. This script overwrites the scaffold
code files (``src/transform.py``, ``tests/test_transform.py``) in place and
commits, without touching README or any other user files.

Usage::

    python -m app.code_repo.refresh_demo_scaffold              # demo repo
    python -m app.code_repo.refresh_demo_scaffold <repo_uuid>   # specific repo
"""
from __future__ import annotations

import argparse
import asyncio
import uuid

from app.code_repo.git_service import _DEMO_REPO_ID, refresh_starter_files


async def _main(repo_id: uuid.UUID) -> None:
    from app.db import SessionLocal  # lazy: don't open DB at import time

    async with SessionLocal() as session:
        changed = await refresh_starter_files(session, repo_id)
        await session.commit()
    if changed:
        print(f"Refreshed scaffold for {repo_id}: {', '.join(changed)}")
    else:
        print(f"Scaffold for {repo_id} already up to date; nothing changed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh a repository's starter scaffold.")
    parser.add_argument(
        "repo_id",
        nargs="?",
        default=str(_DEMO_REPO_ID),
        help="Repository UUID (defaults to the demo repository).",
    )
    args = parser.parse_args()
    asyncio.run(_main(uuid.UUID(args.repo_id)))
