"""high water marks column

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column(
            "high_water_mark",
            sa.Text(),
            nullable=True
        )
    )


def downgrade() -> None:
    op.drop_column("datasets", "high_water_mark")
