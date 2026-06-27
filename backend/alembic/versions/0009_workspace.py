"""workspace items and notebook kinds

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("item_type", sa.Text(), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspace_items.id", ondelete="CASCADE")),
        sa.Column("resource_type", sa.Text()),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("parent_id", "name", name="uq_workspace_sibling_name"),
    )
    op.create_index("ix_workspace_items_parent", "workspace_items", ["parent_id"])
    op.create_index("ix_workspace_items_owner", "workspace_items", ["owner_id"])
    op.create_index("ix_workspace_items_resource", "workspace_items", ["resource_type", "resource_id"])

    op.create_table(
        "workspace_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspace_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True)),
        sa.Column("can_view", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_share", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_manage", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("item_id", "subject_type", "subject_id", name="uq_workspace_item_subject"),
    )
    op.create_index("ix_workspace_permissions_item", "workspace_permissions", ["item_id"])
    op.add_column("notebooks", sa.Column("notebook_kind", sa.Text(), nullable=False, server_default="python"))
    op.alter_column("dashboard_permissions", "subject_id", nullable=True)


def downgrade() -> None:
    op.alter_column("dashboard_permissions", "subject_id", nullable=False)
    op.drop_column("notebooks", "notebook_kind")
    op.drop_index("ix_workspace_permissions_item", table_name="workspace_permissions")
    op.drop_table("workspace_permissions")
    op.drop_index("ix_workspace_items_resource", table_name="workspace_items")
    op.drop_index("ix_workspace_items_owner", table_name="workspace_items")
    op.drop_index("ix_workspace_items_parent", table_name="workspace_items")
    op.drop_table("workspace_items")
