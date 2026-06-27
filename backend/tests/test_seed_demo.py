"""Unit tests for the demo seed.

These hit only the pure ``app.seeds.demo_data`` helpers + the pipeline
compiler, so they run without a DB and without the full app stack.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import yaml

from app.pipelines.compiler import compile_pipeline
from app.seeds.demo_data import (
    DATASET_NAMES,
    DEMO_ONTOLOGY_YAML,
    SCHEMAS,
    TABLE_CUSTOMERS,
    TABLE_ORDERS,
    TABLE_ORDER_ITEMS,
    TABLE_PRODUCTS,
    build_demo_rows,
    ddl_create,
    ddl_drop,
    row_count,
    sample_values,
)


# --------------------------------------------------------------------------
# Volume + determinism
# --------------------------------------------------------------------------


def test_row_counts_are_locked():
    rows = build_demo_rows()
    assert len(rows.customers) == 40
    assert len(rows.products) == 25
    assert len(rows.orders) == 150
    assert len(rows.items) == 400


def test_generation_is_deterministic():
    a = build_demo_rows()
    b = build_demo_rows()
    assert [c["email"] for c in a.customers] == [c["email"] for c in b.customers]
    assert [o["total"] for o in a.orders] == [o["total"] for o in b.orders]


def test_order_totals_match_item_totals():
    rows = build_demo_rows()
    expected: dict[int, Decimal] = {}
    for it in rows.items:
        expected[it["order_id"]] = expected.get(it["order_id"], Decimal("0.00")) + (
            it["unit_price"] * it["quantity"]
        )
    for o in rows.orders:
        want = expected.get(o["id"], Decimal("0.00")).quantize(Decimal("0.01"))
        assert o["total"] == want, f"order {o['id']} total mismatch"


def test_every_order_has_a_real_customer():
    rows = build_demo_rows()
    customer_ids = {c["id"] for c in rows.customers}
    for o in rows.orders:
        assert o["customer_id"] in customer_ids


def test_every_item_points_at_a_real_order_and_product():
    rows = build_demo_rows()
    order_ids = {o["id"] for o in rows.orders}
    product_ids = {p["id"] for p in rows.products}
    for it in rows.items:
        assert it["order_id"] in order_ids
        assert it["product_id"] in product_ids


# --------------------------------------------------------------------------
# Schema + DDL shape
# --------------------------------------------------------------------------


def test_schemas_cover_every_dataset():
    assert set(SCHEMAS.keys()) == set(DATASET_NAMES.keys())
    for cols in SCHEMAS.values():
        assert any(name == "id" for name, _sql, _ftype in cols)


def test_ddl_create_emits_idempotent_statements():
    stmts = ddl_create()
    assert len(stmts) == 4
    for s in stmts:
        assert "CREATE TABLE IF NOT EXISTS" in s
        assert '"public".' in s


def test_ddl_drop_order_respects_foreign_keys():
    # Drop must remove dependents before dependencies.
    stmts = ddl_drop()
    text = " ".join(stmts)
    assert text.index("demo_order_items") < text.index("demo_orders")
    assert text.index("demo_orders") < text.index("demo_customers")


def test_sample_values_pulls_distinct_entries():
    rows = build_demo_rows()
    countries = sample_values(rows.customers, "country", n=3)
    assert len(countries) == len(set(countries))
    assert all(isinstance(c, str) for c in countries)


# --------------------------------------------------------------------------
# Ontology YAML
# --------------------------------------------------------------------------


def test_ontology_yaml_is_valid():
    data = yaml.safe_load(DEMO_ONTOLOGY_YAML)
    assert "objects" in data
    objs = data["objects"]
    assert set(objs.keys()) == {"Customer", "Order", "OrderItem", "Product"}
    # Tables reference the demo_* tables, not the friendly catalog names.
    assert objs["Customer"]["table"] == TABLE_CUSTOMERS
    assert objs["Order"]["table"] == TABLE_ORDERS
    assert objs["OrderItem"]["table"] == TABLE_ORDER_ITEMS
    assert objs["Product"]["table"] == TABLE_PRODUCTS


def test_ontology_yaml_relationships_are_complete():
    data = yaml.safe_load(DEMO_ONTOLOGY_YAML)
    rels: list[tuple[str, str, str]] = []
    for src, spec in data["objects"].items():
        for name, rel in (spec.get("relationships") or {}).items():
            rels.append((src, rel["target"], rel["type"]))
    assert ("Customer", "Order", "one_to_many") in rels
    assert ("Order", "OrderItem", "one_to_many") in rels
    assert ("OrderItem", "Product", "many_to_one") in rels


# --------------------------------------------------------------------------
# Pipeline compiles
# --------------------------------------------------------------------------


def test_seeded_pipeline_compiles_to_valid_sql():
    """The Customers ⋈ Orders → Output graph the seed inserts should compile
    to a real SELECT through the production compiler, given the seeded schemas.
    """
    from dataclasses import dataclass

    @dataclass
    class _DS:
        id: object
        schema_name: str
        table_name: str

    @dataclass
    class _Col:
        name: str

    cust = _DS(id=uuid4(), schema_name="public", table_name=TABLE_CUSTOMERS)
    ords = _DS(id=uuid4(), schema_name="public", table_name=TABLE_ORDERS)
    cust_cols = [_Col(c[0]) for c in SCHEMAS[TABLE_CUSTOMERS]]
    ord_cols = [_Col(c[0]) for c in SCHEMAS[TABLE_ORDERS]]

    nodes = [
        {"id": "sc", "node_type": "source", "config": {"dataset_id": str(cust.id)}},
        {"id": "so", "node_type": "source", "config": {"dataset_id": str(ords.id)}},
        {
            "id": "j",
            "node_type": "join",
            "config": {"join_type": "inner", "left_keys": ["id"], "right_keys": ["customer_id"]},
        },
        {"id": "out", "node_type": "output", "config": {"name": "customer_orders"}},
    ]
    edges = [
        {"id": "e1", "source_node_id": "sc", "target_node_id": "j", "target_handle": "left"},
        {"id": "e2", "source_node_id": "so", "target_node_id": "j", "target_handle": "right"},
        {"id": "e3", "source_node_id": "j", "target_node_id": "out", "target_handle": "in"},
    ]
    compiled = compile_pipeline(
        nodes=nodes,
        edges=edges,
        datasets=[cust, ords],
        dataset_columns_by_id={cust.id: cust_cols, ords.id: ord_cols},
    )
    assert "INNER JOIN" in compiled.sql
    assert 'l."id" = r."customer_id"' in compiled.sql
    # Both source dataset ids are referenced.
    assert {cust.id, ords.id} == set(compiled.dataset_ids)
    # Left.id is preserved; right.id collides with left and gets the `_r` suffix.
    assert "id_r" in compiled.output_columns


# --------------------------------------------------------------------------
# Cross-check row_count helper matches the generator
# --------------------------------------------------------------------------


def test_row_count_helper_matches_generator():
    rows = build_demo_rows()
    assert row_count(TABLE_CUSTOMERS, rows) == 40
    assert row_count(TABLE_PRODUCTS, rows) == 25
    assert row_count(TABLE_ORDERS, rows) == 150
    assert row_count(TABLE_ORDER_ITEMS, rows) == 400
