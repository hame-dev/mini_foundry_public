"""security markings column

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column(
            "security_markings",
            postgresql.JSONB(),
            nullable=False,
            server_default='[]'
        )
    )
    op.add_column(
        "users",
        sa.Column(
            "security_markings",
            postgresql.JSONB(),
            nullable=False,
            server_default='[]'
        )
    )


def downgrade() -> None:
    op.drop_column("datasets", "security_markings")
    op.drop_column("users", "security_markings")
