"""physical dataset branching

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "branch_transactions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("branch_name", sa.Text(), nullable=False),
        sa.Column("parent_branch", sa.Text(), nullable=False, server_default="main"),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("merged_into", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_branch_transactions_dataset_id", "branch_transactions", ["dataset_id"])
    op.create_index("ix_branch_transactions_branch_name", "branch_transactions", ["branch_name"])


def downgrade() -> None:
    op.drop_table("branch_transactions")
