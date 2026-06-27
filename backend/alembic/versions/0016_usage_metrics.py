"""create usage metrics table

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_metrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False
        ),
        sa.Column(
            "resource_type",
            sa.Text(),
            nullable=False
        ),
        sa.Column(
            "resource_id",
            sa.Text(),
            nullable=True
        ),
        sa.Column(
            "compute_credits",
            sa.Float(),
            nullable=False,
            server_default="0.0"
        ),
        sa.Column(
            "execution_time_ms",
            sa.Integer(),
            nullable=False,
            server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=False
        )
    )


def downgrade() -> None:
    op.drop_table("usage_metrics")
