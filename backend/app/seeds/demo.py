"""Demo seed: a small e-commerce dataset that lights up every UI surface.

After this runs once, an admin sees:

* a ``demo_ecommerce`` DataSource of ``source_type = "postgres"``
* four Datasets — ``customers`` / ``orders`` / ``order_items`` / ``products`` —
  whose physical tables (``public.demo_*``) are created and populated by this
  module
* an Ontology with four object types and three relationships connecting them
* one example Pipeline that joins customers with orders

Re-running the seed is a no-op (idempotent guard on the DataSource name);
pass ``force=True`` to drop and recreate everything.

Pure data helpers (deterministic row generation, schemas, YAML) live in
:mod:`app.seeds.demo_data` and have no app/SQLAlchemy/pydantic-settings
dependencies, so unit tests can import them anywhere.
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from typing import Any

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.models import Dataset, DatasetColumn, DataSource
from app.ontology.models import OntologyObject, OntologyRelationship
from app.pipelines.models import Pipeline, PipelineEdge, PipelineNode
from app.seeds.demo_data import (
    DATASET_NAMES,
    DEMO_ONTOLOGY_YAML,
    DemoRows,
    SCHEMAS,
    TABLE_CUSTOMERS,
    TABLE_ORDERS,
    build_demo_rows,
    ddl_create,
    ddl_drop,
    row_count,
    rows_for,
    sample_values,
)


DEMO_SOURCE_NAME = "demo_ecommerce"
DEMO_PIPELINE_NAME = "Customer orders"


# --------------------------------------------------------------------------
# Physical DDL + DML (sync engine, separate from the async ORM session)
# --------------------------------------------------------------------------


def _insert_rows(conn, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    cols = [name for name, _sql, _ftype in SCHEMAS[table]]
    placeholders = ", ".join(f":{c}" for c in cols)
    quoted = ", ".join(f'"{c}"' for c in cols)
    stmt = text(
        f'INSERT INTO "public"."{table}" ({quoted}) VALUES ({placeholders}) '
        f"ON CONFLICT (id) DO NOTHING"
    )
    conn.execute(stmt, rows)


def materialize_physical_tables(rows: DemoRows, *, drop_first: bool) -> None:
    """Create the four ``demo_*`` tables and INSERT the synthetic rows.

    All DDL/DML runs inside a single ``engine.begin()`` transaction.
    """
    from app.config import get_settings

    settings = get_settings()
    engine = create_engine(settings.sync_database_url)
    with engine.begin() as conn:
        if drop_first:
            for stmt in ddl_drop():
                conn.execute(text(stmt))
        for stmt in ddl_create():
            conn.execute(text(stmt))
        from app.seeds.demo_data import (
            TABLE_CUSTOMERS as TC,
            TABLE_PRODUCTS as TP,
            TABLE_ORDERS as TO,
            TABLE_ORDER_ITEMS as TI,
        )
        _insert_rows(conn, TC, rows.customers)
        _insert_rows(conn, TP, rows.products)
        _insert_rows(conn, TO, rows.orders)
        _insert_rows(conn, TI, rows.items)


# --------------------------------------------------------------------------
# ORM registration helpers
# --------------------------------------------------------------------------


async def _register_datasets(
    session: AsyncSession,
    *,
    source: DataSource,
    rows: DemoRows,
    admin_user_id: uuid.UUID,
) -> dict[str, Dataset]:
    from app.platform.service import upsert_resource

    out: dict[str, Dataset] = {}
    for table, friendly in DATASET_NAMES.items():
        ds = Dataset(
            source_id=source.id,
            name=friendly,
            description=f"Demo {friendly} table",
            schema_name="public",
            table_name=table,
            row_count=row_count(table, rows),
            ai_policy="local_only",
            execution_engine="postgres",
            owner_id=admin_user_id,
        )
        session.add(ds)
        await session.flush()
        out[table] = ds

        sample_source = rows_for(table, rows)
        for col_name, _sql_type, ftype in SCHEMAS[table]:
            session.add(
                DatasetColumn(
                    dataset_id=ds.id,
                    name=col_name,
                    data_type=ftype,
                    sample_values=sample_values(sample_source, col_name),
                )
            )
        # Register the platform resource + owner ACL (admins additionally get
        # full capabilities via the admin-role bypass in enforcement).
        await upsert_resource(
            session,
            resource_type="dataset",
            object_id=ds.id,
            name=ds.name,
            owner_user_id=admin_user_id,
            metadata={"schema_name": ds.schema_name, "table_name": ds.table_name},
        )
    await session.flush()
    return out


async def _build_demo_pipeline(
    session: AsyncSession,
    *,
    datasets: dict[str, Dataset],
    admin_user_id: uuid.UUID,
) -> Pipeline:
    """Construct a Customers ⋈ Orders → Output pipeline.

    The graph is the same JSON shape the canvas produces, so opening it in
    /pipelines/[id] just works.
    """
    pipeline = Pipeline(
        name=DEMO_PIPELINE_NAME,
        description="Demo pipeline: every customer joined to their orders.",
        owner_id=admin_user_id,
        graph={"viewport": {"x": 0, "y": 0, "zoom": 1}},
        ai_policy="local_only",
    )
    session.add(pipeline)
    await session.flush()

    src_customers = PipelineNode(
        pipeline_id=pipeline.id,
        node_type="source",
        position={"x": 80, "y": 80},
        config={"dataset_id": str(datasets[TABLE_CUSTOMERS].id)},
    )
    src_orders = PipelineNode(
        pipeline_id=pipeline.id,
        node_type="source",
        position={"x": 80, "y": 260},
        config={"dataset_id": str(datasets[TABLE_ORDERS].id)},
    )
    join_node = PipelineNode(
        pipeline_id=pipeline.id,
        node_type="join",
        position={"x": 420, "y": 170},
        config={
            "join_type": "inner",
            "left_keys": ["id"],
            "right_keys": ["customer_id"],
        },
    )
    output_node = PipelineNode(
        pipeline_id=pipeline.id,
        node_type="output",
        position={"x": 760, "y": 170},
        config={
            "name": "customer_orders",
            "description": "Customers joined with their orders",
            "materialize": "view",
        },
    )
    session.add_all([src_customers, src_orders, join_node, output_node])
    await session.flush()

    session.add_all([
        PipelineEdge(
            pipeline_id=pipeline.id,
            source_node_id=src_customers.id,
            target_node_id=join_node.id,
            target_handle="left",
        ),
        PipelineEdge(
            pipeline_id=pipeline.id,
            source_node_id=src_orders.id,
            target_node_id=join_node.id,
            target_handle="right",
        ),
        PipelineEdge(
            pipeline_id=pipeline.id,
            source_node_id=join_node.id,
            target_node_id=output_node.id,
            target_handle="in",
        ),
    ])
    await session.flush()
    return pipeline


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


async def _existing_source(session: AsyncSession) -> DataSource | None:
    res = await session.execute(select(DataSource).where(DataSource.name == DEMO_SOURCE_NAME))
    return res.scalar_one_or_none()


async def _wipe_existing(session: AsyncSession, source: DataSource) -> None:
    """Drop any pre-existing demo Pipelines and ontology rows pointing at the
    demo Datasets, then delete the DataSource (which cascades to Datasets and
    DatasetColumns).
    """
    await session.execute(delete(Pipeline).where(Pipeline.name == DEMO_PIPELINE_NAME))

    demo_ds_q = await session.execute(
        select(Dataset.id, Dataset.table_name).where(Dataset.source_id == source.id)
    )
    demo_rows = list(demo_ds_q.all())
    demo_ds_ids = [r[0] for r in demo_rows]
    if demo_ds_ids:
        obj_q = await session.execute(
            select(OntologyObject.type_name).where(OntologyObject.dataset_id.in_(demo_ds_ids))
        )
        type_names = [r[0] for r in obj_q.all()]
        if type_names:
            await session.execute(
                delete(OntologyRelationship).where(
                    (OntologyRelationship.source_type.in_(type_names))
                    | (OntologyRelationship.target_type.in_(type_names))
                )
            )
            await session.execute(
                delete(OntologyObject).where(OntologyObject.type_name.in_(type_names))
            )

    await session.delete(source)
    await session.flush()


# --------------------------------------------------------------------------
# Public entrypoint
# --------------------------------------------------------------------------


async def seed_demo(session: AsyncSession, *, force: bool = False) -> dict[str, Any]:
    """Seed the demo dataset. Idempotent unless ``force=True``."""
    from app.auth.service import get_or_create_role, get_user_by_email
    from app.config import get_settings
    from app.ontology.yaml_import import import_yaml

    settings = get_settings()

    existing = await _existing_source(session)
    if existing is not None and not force:
        return {"created": False, "datasets": 0, "ontology_objects": 0, "pipeline_id": None}

    admin = await get_user_by_email(session, settings.admin_email)
    if admin is None:
        return {"created": False, "error": "admin user not seeded yet"}
    await get_or_create_role(session, "admin")

    if existing is not None and force:
        await _wipe_existing(session, existing)

    rows = build_demo_rows()
    # Physical DDL + INSERT outside the async session.
    materialize_physical_tables(rows, drop_first=force)

    source = DataSource(
        name=DEMO_SOURCE_NAME,
        source_type="postgres",
        connection_config={"schema": "public", "managed": True},
        status="ok",
        owner_id=admin.id,
    )
    session.add(source)
    await session.flush()

    datasets = await _register_datasets(
        session,
        source=source,
        rows=rows,
        admin_user_id=admin.id,
    )

    ontology_summary = await import_yaml(session, DEMO_ONTOLOGY_YAML)
    pipeline = await _build_demo_pipeline(
        session, datasets=datasets, admin_user_id=admin.id
    )

    await session.commit()

    return {
        "created": True,
        "datasets": len(datasets),
        "ontology_objects": ontology_summary.get("objects", 0),
        "pipeline_id": str(pipeline.id),
    }


# --------------------------------------------------------------------------
# CLI: python -m app.seeds.demo [--force]
# --------------------------------------------------------------------------


async def _main(force: bool) -> None:
    from app.db import SessionLocal  # lazy: don't open DB at import time

    async with SessionLocal() as session:
        summary = await seed_demo(session, force=force)
    print(summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Mini Foundry demo data.")
    parser.add_argument("--force", action="store_true", help="Drop and recreate the demo data.")
    args = parser.parse_args()
    asyncio.run(_main(args.force))
