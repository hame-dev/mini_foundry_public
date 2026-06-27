"""dataset quality results + freshness window

Revision ID: 0031
Revises: 0030
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("freshness_window_seconds", sa.Integer(), nullable=True))
    op.create_table(
        "quality_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expectation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), server_default="error", nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("failed_records", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_quality_results_dataset", "quality_results", ["dataset_id", "run_id"])


def downgrade() -> None:
    op.drop_index("ix_quality_results_dataset", table_name="quality_results")
    op.drop_table("quality_results")
    op.drop_column("datasets", "freshness_window_seconds")
