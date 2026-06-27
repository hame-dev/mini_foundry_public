"""action governance controls

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ontology_actions", sa.Column("approval_required", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("ontology_actions", sa.Column("preconditions", postgresql.JSONB(), nullable=True))
    op.alter_column("action_permissions", "subject_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("action_runs", sa.Column("approval_request_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_action_runs_approval_request",
        "action_runs",
        "approval_requests",
        ["approval_request_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_action_runs_approval_request", "action_runs", type_="foreignkey")
    op.drop_column("action_runs", "approval_request_id")
    op.alter_column("action_permissions", "subject_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_column("ontology_actions", "preconditions")
    op.drop_column("ontology_actions", "approval_required")
