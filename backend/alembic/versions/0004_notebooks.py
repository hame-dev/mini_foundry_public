"""notebooks + cells + permissions

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notebooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("ai_policy", sa.Text(), nullable=False, server_default="local_only"),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "notebook_cells",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("notebook_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("cell_type", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default=""),
        sa.Column("dataset_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False, server_default=sa.text("'{}'::uuid[]")),
        sa.Column("last_output", postgresql.JSONB()),
        sa.Column("last_run_at", sa.TIMESTAMP()),
        sa.Column("last_status", sa.Text()),
        sa.Column("last_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.UniqueConstraint("notebook_id", "position", name="uq_notebook_cell_position"),
    )
    op.create_index("ix_notebook_cells_notebook", "notebook_cells", ["notebook_id"])

    op.create_table(
        "notebook_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("notebook_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("can_view", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_edit", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_run", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_manage", sa.Boolean(), server_default=sa.text("false")),
        sa.UniqueConstraint("notebook_id", "subject_type", "subject_id", name="uq_notebook_subject"),
    )


def downgrade() -> None:
    op.drop_table("notebook_permissions")
    op.drop_index("ix_notebook_cells_notebook", table_name="notebook_cells")
    op.drop_table("notebook_cells")
    op.drop_table("notebooks")
