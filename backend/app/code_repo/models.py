import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CodeRepository(Base):
    __tablename__ = "code_repositories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    repo_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="python_transforms")
    default_branch: Mapped[str] = mapped_column(Text, nullable=False, server_default="main")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    git_path: Mapped[str | None] = mapped_column(Text)  # path to bare git repo on disk
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=text("now()"), nullable=False
    )


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("code_repositories.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_branch: Mapped[str] = mapped_column(Text, nullable=False)
    target_branch: Mapped[str] = mapped_column(Text, server_default="main", nullable=False)
    status: Mapped[str] = mapped_column(
        Text, server_default="open", nullable=False
    )  # open | approved | merged | closed
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    comments: Mapped[list | None] = mapped_column(JSONB)  # [{line, file, author, body, created_at}]
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=text("now()"), nullable=False
    )
    merged_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
