"""oidc branch ml lineage controls

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oidc_login_states",
        sa.Column("state_hash", sa.Text(), nullable=False),
        sa.Column("nonce_hash", sa.Text(), nullable=False),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("consumed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("state_hash"),
    )
    op.create_index("ix_oidc_login_states_expires", "oidc_login_states", ["expires_at"])

    op.add_column("ml_models", sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("ml_model_versions", sa.Column("training_dataset_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("ml_model_versions", sa.Column("artifact_manifest", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column("ml_model_versions", sa.Column("approval_status", sa.Text(), server_default="draft", nullable=False))
    op.add_column("ml_model_versions", sa.Column("promoted_at", sa.TIMESTAMP(), nullable=True))
    op.add_column("ml_model_versions", sa.Column("promoted_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_ml_models_current_version", "ml_models", "ml_model_versions", ["current_version_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_ml_model_versions_training_dataset_version", "ml_model_versions", "dataset_versions", ["training_dataset_version_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_ml_model_versions_promoted_by", "ml_model_versions", "users", ["promoted_by"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_ml_model_versions_promoted_by", "ml_model_versions", type_="foreignkey")
    op.drop_constraint("fk_ml_model_versions_training_dataset_version", "ml_model_versions", type_="foreignkey")
    op.drop_constraint("fk_ml_models_current_version", "ml_models", type_="foreignkey")
    op.drop_column("ml_model_versions", "promoted_by")
    op.drop_column("ml_model_versions", "promoted_at")
    op.drop_column("ml_model_versions", "approval_status")
    op.drop_column("ml_model_versions", "artifact_manifest")
    op.drop_column("ml_model_versions", "training_dataset_version_id")
    op.drop_column("ml_models", "current_version_id")
    op.drop_index("ix_oidc_login_states_expires", table_name="oidc_login_states")
    op.drop_table("oidc_login_states")
