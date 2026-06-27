import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


NODE_TYPES = {"source", "join", "union", "filter", "formula", "select", "trained_model", "output"}
JOIN_TYPES = {"inner", "left", "right", "full"}


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    # JSON payload for canvas-only state (viewport, etc.); nodes/edges live in separate tables
    graph: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ai_policy: Mapped[str] = mapped_column(Text, server_default="local_only", nullable=False)
    output_saved_query_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("saved_queries.id", ondelete="SET NULL")
    )
    output_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL")
    )
    # view | table | parquet
    materialization_type: Mapped[str] = mapped_column(Text, server_default="view", nullable=False)
    materialized_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    materialized_rows: Mapped[int | None] = mapped_column()
    last_run_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    last_run_status: Mapped[str | None] = mapped_column(Text)
    last_run_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("now()"), nullable=False)


class PipelineNode(Base):
    __tablename__ = "pipeline_nodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False
    )
    node_type: Mapped[str] = mapped_column(Text, nullable=False)  # NODE_TYPES
    position: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("now()"), nullable=False)


class PipelineEdge(Base):
    __tablename__ = "pipeline_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_nodes.id", ondelete="CASCADE"), nullable=False
    )
    # 'left' | 'right' for join nodes; 'in' for single-input nodes
    target_handle: Mapped[str] = mapped_column(Text, server_default="in", nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, server_default=text("now()"), nullable=False)

