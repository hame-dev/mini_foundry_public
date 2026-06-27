"""pipeline physical materialization type

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pipelines", sa.Column("materialization_type", sa.Text(), nullable=False, server_default="view"))
    op.add_column("pipelines", sa.Column("materialized_at", sa.TIMESTAMP(), nullable=True))
    op.add_column("pipelines", sa.Column("materialized_rows", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipelines", "materialized_rows")
    op.drop_column("pipelines", "materialized_at")
    op.drop_column("pipelines", "materialization_type")
