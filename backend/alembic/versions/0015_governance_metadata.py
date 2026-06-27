"""governance metadata columns

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column(
            "stewards",
            postgresql.JSONB(),
            nullable=False,
            server_default='[]'
        )
    )
    op.add_column(
        "datasets",
        sa.Column(
            "tags",
            postgresql.JSONB(),
            nullable=False,
            server_default='[]'
        )
    )
    op.add_column(
        "datasets",
        sa.Column(
            "glossary_terms",
            postgresql.JSONB(),
            nullable=False,
            server_default='[]'
        )
    )


def downgrade() -> None:
    op.drop_column("datasets", "stewards")
    op.drop_column("datasets", "tags")
    op.drop_column("datasets", "glossary_terms")
