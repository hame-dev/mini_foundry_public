"""phase 2 — object sets + functions on objects

Foundry-core-parity ontology slice. Two new tables:

* ``ontology_functions`` — computed (derived) read-only properties on an object
  type, stored as a validated scalar SQL expression over the object's own columns.
* ``ontology_object_sets`` — saved, governed, filterable collections of objects.
  Filters are structured predicates (never raw SQL); data access is still enforced
  through ``governed_query`` and the set itself is an ACL'd ``Resource``.

Revision ID: 0035
Revises: 0034
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ontology_functions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("expression", sa.Text(), nullable=False),
        sa.Column("return_type", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("object_type", "name", name="uq_ontology_function_type_name"),
    )
    op.create_index("ix_ontology_functions_object_type", "ontology_functions", ["object_type"])

    op.create_table(
        "ontology_object_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("branch_name", sa.Text(), server_default="main", nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("object_type", "name", name="uq_ontology_object_set_type_name"),
    )
    op.create_index("ix_ontology_object_sets_object_type", "ontology_object_sets", ["object_type"])


def downgrade() -> None:
    op.drop_index("ix_ontology_object_sets_object_type", table_name="ontology_object_sets")
    op.drop_table("ontology_object_sets")
    op.drop_index("ix_ontology_functions_object_type", table_name="ontology_functions")
    op.drop_table("ontology_functions")
