"""foundry redesign contracts

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dashboards", sa.Column("dashboard_kind", sa.Text(), server_default="contour", nullable=False))
    op.add_column("notebooks", sa.Column("requirements", postgresql.JSONB(), nullable=True))
    op.add_column("notebooks", sa.Column("kernel_name", sa.Text(), nullable=True))
    op.add_column("notebooks", sa.Column("workspace_metadata", postgresql.JSONB(), nullable=True))
    op.add_column("code_repositories", sa.Column("repo_type", sa.Text(), server_default="python_transforms", nullable=False))
    op.add_column("code_repositories", sa.Column("default_branch", sa.Text(), server_default="main", nullable=False))

    op.create_table(
        "resource_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("favorite", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("resource_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("last_viewed_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "resource_type", "resource_id", name="uq_resource_activity_user_resource"),
    )
    op.create_index("ix_resource_activity_user_recent", "resource_activity", ["user_id", "last_viewed_at"])
    op.create_index("ix_resource_activity_user_favorite", "resource_activity", ["user_id", "favorite"])

    op.create_table(
        "user_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("setting_key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "setting_key", name="uq_user_setting_key"),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
    op.drop_index("ix_resource_activity_user_favorite", table_name="resource_activity")
    op.drop_index("ix_resource_activity_user_recent", table_name="resource_activity")
    op.drop_table("resource_activity")
    op.drop_column("code_repositories", "default_branch")
    op.drop_column("code_repositories", "repo_type")
    op.drop_column("notebooks", "workspace_metadata")
    op.drop_column("notebooks", "kernel_name")
    op.drop_column("notebooks", "requirements")
    op.drop_column("dashboards", "dashboard_kind")
