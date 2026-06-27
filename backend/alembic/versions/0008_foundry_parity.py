"""foundry parity lifecycle + models

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dashboards", sa.Column("published_layout", postgresql.JSONB()))
    op.add_column("dashboards", sa.Column("published_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("dashboards", sa.Column("published_at", sa.TIMESTAMP()))
    op.add_column("dashboards", sa.Column("draft_updated_at", sa.TIMESTAMP()))

    op.create_table(
        "ml_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("model_type", sa.Text(), nullable=False, server_default="baseline"),
        sa.Column("input_dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="SET NULL")),
        sa.Column("target_column", sa.Text(), nullable=False),
        sa.Column("feature_columns", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ml_models_owner", "ml_models", ["owner_id"])

    op.create_table(
        "ml_model_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("training_config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metrics", postgresql.JSONB()),
        sa.Column("artifact_path", sa.Text()),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("trained_at", sa.TIMESTAMP()),
        sa.UniqueConstraint("model_id", "version", name="uq_ml_model_version"),
    )
    op.create_index("ix_ml_model_versions_model", "ml_model_versions", ["model_id"])


def downgrade() -> None:
    op.drop_index("ix_ml_model_versions_model", table_name="ml_model_versions")
    op.drop_table("ml_model_versions")
    op.drop_index("ix_ml_models_owner", table_name="ml_models")
    op.drop_table("ml_models")
    op.drop_column("dashboards", "draft_updated_at")
    op.drop_column("dashboards", "published_at")
    op.drop_column("dashboards", "published_version")
    op.drop_column("dashboards", "published_layout")
