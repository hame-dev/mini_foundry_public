"""datasets.execution_engine + storage_uri

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("execution_engine", sa.Text(), nullable=False, server_default="postgres"),
    )
    op.add_column("datasets", sa.Column("storage_uri", sa.Text()))
    op.create_check_constraint(
        "ck_datasets_execution_engine",
        "datasets",
        "execution_engine IN ('postgres', 'duckdb', 'spark')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_datasets_execution_engine", "datasets", type_="check")
    op.drop_column("datasets", "storage_uri")
    op.drop_column("datasets", "execution_engine")
