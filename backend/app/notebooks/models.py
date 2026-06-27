import uuid
from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, Integer, Text, TIMESTAMP, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Notebook(Base):
    __tablename__ = "notebooks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    ai_policy: Mapped[str] = mapped_column(Text, nullable=False, server_default="local_only")
    notebook_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="python")
    requirements: Mapped[list | None] = mapped_column(JSONB)
    kernel_name: Mapped[str | None] = mapped_column(Text)
    workspace_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("now()"), nullable=False)


class NotebookCell(Base):
    __tablename__ = "notebook_cells"
    __table_args__ = (UniqueConstraint("notebook_id", "position", name="uq_notebook_cell_position"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    notebook_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    cell_type: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    dataset_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    last_output: Mapped[dict | None] = mapped_column(JSONB)
    last_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    last_status: Mapped[str | None] = mapped_column(Text)
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"))


class NotebookPermission(Base):
    __tablename__ = "notebook_permissions"
    __table_args__ = (UniqueConstraint("notebook_id", "subject_type", "subject_id", name="uq_notebook_subject"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    notebook_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    can_edit: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    can_run: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    can_manage: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


CELL_TYPES = {"markdown", "sql", "python", "ai_prompt"}
NOTEBOOK_KINDS = {"sql", "python"}
KIND_CELL_TYPES = {
    "sql": {"markdown", "sql"},
    "python": {"markdown", "python", "ai_prompt"},
}
