"""phase 1 kernel consolidation

Drop the legacy ``dataset_permissions`` table (enforcement is ResourceACL-only;
existing grants were already backfilled into ``resource_acl`` by 0033) and add a
unified ``lifecycle_state`` to ``resources``.

Revision ID: 0034
Revises: 0033
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Item 7: unified resource lifecycle state -------------------------
    op.add_column(
        "resources",
        sa.Column("lifecycle_state", sa.Text(), server_default="draft", nullable=False),
    )
    # Existing resources are considered published; deprecated datasets inherit
    # the deprecated state from their feature row.
    op.execute("UPDATE resources SET lifecycle_state = 'published'")
    op.execute(
        """
        UPDATE resources r
        SET lifecycle_state = 'deprecated'
        FROM datasets d
        WHERE r.resource_type = 'dataset'
          AND r.object_id = d.id
          AND d.deprecated_at IS NOT NULL
        """
    )

    # --- Item 2: drop the legacy dataset_permissions table ----------------
    op.drop_table("dataset_permissions")


def downgrade() -> None:
    op.create_table(
        "dataset_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("can_view_metadata", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_view_data", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_use_in_sql", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_use_in_python", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_use_with_ai", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_export", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_edit", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("can_manage", sa.Boolean(), server_default=sa.text("false")),
        sa.UniqueConstraint("dataset_id", "subject_type", "subject_id", name="uq_dataset_subject"),
    )
    op.drop_column("resources", "lifecycle_state")
