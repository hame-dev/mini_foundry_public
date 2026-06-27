"""ontology action validation rules and webhook

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ontology_actions", sa.Column("validation_rules", postgresql.JSONB(), nullable=True))
    op.add_column("ontology_actions", sa.Column("webhook_url", sa.Text(), nullable=True))
    op.add_column("ontology_actions", sa.Column("webhook_secret", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ontology_actions", "webhook_secret")
    op.drop_column("ontology_actions", "webhook_url")
    op.drop_column("ontology_actions", "validation_rules")
