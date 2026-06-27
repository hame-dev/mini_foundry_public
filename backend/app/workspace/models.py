import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Text, TIMESTAMP, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


WORKSPACE_ITEM_TYPES = {
    "folder",
    "sql",
    "notebook",
    "code_repository",
    "dashboard",
    "pipeline",
    "model",
    "ontology",
    "dataset_link",
}


class WorkspaceItem(Base):
    __tablename__ = "workspace_items"
    __table_args__ = (UniqueConstraint("parent_id", "name", name="uq_workspace_sibling_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workspace_items.id", ondelete="CASCADE"))
    resource_type: Mapped[str | None] = mapped_column(Text)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("now()"), nullable=False)


class WorkspacePermission(Base):
    __tablename__ = "workspace_permissions"
    __table_args__ = (UniqueConstraint("item_id", "subject_type", "subject_id", name="uq_workspace_item_subject"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspace_items.id", ondelete="CASCADE"), nullable=False)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    can_view: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    can_edit: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    can_run: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    can_share: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    can_manage: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
