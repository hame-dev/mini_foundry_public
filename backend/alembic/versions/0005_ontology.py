"""ontology objects + relationships + actions + permissions

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ontology_objects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("type_name", sa.Text(), nullable=False, unique=True),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("primary_key", sa.Text(), nullable=False),
        sa.Column("display_name_column", sa.Text()),
        sa.Column("properties", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "ontology_relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("cardinality", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.UniqueConstraint("source_type", "name", name="uq_ontology_rel_source_name"),
    )
    op.create_index("ix_ontology_rel_source", "ontology_relationships", ["source_type"])

    op.create_table(
        "ontology_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("workflow_key", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("input_schema", postgresql.JSONB()),
        sa.Column("object_type", sa.Text()),                          # optional: scope to an ontology type
        sa.Column("requires_capability", sa.Text(), server_default="can_run_action"),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "action_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("action_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("can_run", sa.Boolean(), server_default=sa.text("false")),
        sa.UniqueConstraint("action_id", "subject_type", "subject_id", name="uq_action_subject"),
    )


def downgrade() -> None:
    op.drop_table("action_permissions")
    op.drop_table("ontology_actions")
    op.drop_index("ix_ontology_rel_source", table_name="ontology_relationships")
    op.drop_table("ontology_relationships")
    op.drop_table("ontology_objects")
