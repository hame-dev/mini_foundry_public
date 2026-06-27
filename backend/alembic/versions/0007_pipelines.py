"""pipelines + ontology_layouts + mf_pipelines schema

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Managed schema for materialized pipeline views.
    op.execute('CREATE SCHEMA IF NOT EXISTS "mf_pipelines"')

    op.create_table(
        "pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("graph", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ai_policy", sa.Text(), nullable=False, server_default="local_only"),
        sa.Column("output_saved_query_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("saved_queries.id", ondelete="SET NULL")),
        sa.Column("output_dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="SET NULL")),
        sa.Column("last_run_at", sa.TIMESTAMP()),
        sa.Column("last_run_status", sa.Text()),
        sa.Column("last_run_error", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_pipelines_owner", "pipelines", ["owner_id"])

    op.create_table(
        "pipeline_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("position", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_pipeline_nodes_pipeline", "pipeline_nodes", ["pipeline_id"])

    op.create_table(
        "pipeline_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipeline_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipeline_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_handle", sa.Text(), nullable=False, server_default="in"),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_pipeline_edges_pipeline", "pipeline_edges", ["pipeline_id"])

    op.create_table(
        "ontology_layouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("positions", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("viewport", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ontology_layouts")
    op.drop_index("ix_pipeline_edges_pipeline", table_name="pipeline_edges")
    op.drop_table("pipeline_edges")
    op.drop_index("ix_pipeline_nodes_pipeline", table_name="pipeline_nodes")
    op.drop_table("pipeline_nodes")
    op.drop_index("ix_pipelines_owner", table_name="pipelines")
    op.drop_table("pipelines")
    op.execute('DROP SCHEMA IF EXISTS "mf_pipelines" CASCADE')
