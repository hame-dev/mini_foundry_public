"""dataset branching and expectations

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add branch_name and transaction_id to datasets
    op.add_column("datasets", sa.Column("branch_name", sa.Text(), nullable=False, server_default="main"))
    op.add_column("datasets", sa.Column("transaction_id", sa.Text()))

    # 2. Create expectations table
    op.create_table(
        "expectations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("column_name", sa.Text()),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column("rule_value", sa.Text()),
        sa.Column("severity", sa.Text(), nullable=False, server_default="error"),
        sa.Column("created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_expectations_dataset", "expectations", ["dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_expectations_dataset", table_name="expectations")
    op.drop_table("expectations")
    op.drop_column("datasets", "transaction_id")
    op.drop_column("datasets", "branch_name")
