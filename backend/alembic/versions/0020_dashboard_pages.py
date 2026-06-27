"""dashboard pages and variables schema

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dashboards", sa.Column("pages", postgresql.JSONB(), nullable=True))
    op.add_column("dashboards", sa.Column("variables_schema", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("dashboards", "variables_schema")
    op.drop_column("dashboards", "pages")
