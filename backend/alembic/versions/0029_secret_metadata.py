"""secret name/description metadata

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("secrets", sa.Column("name", sa.Text(), nullable=True))
    op.add_column("secrets", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("secrets", "description")
    op.drop_column("secrets", "name")
