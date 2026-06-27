"""Pure helpers for the demo seed.

Everything in this module is dependency-free (only stdlib + ``yaml`` are
imported), so unit tests can import it without bringing the full app
runtime (SQLAlchemy 2.x, pydantic-settings, etc.).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any


# Physical table names — all live in `public` and are prefixed `demo_` so they
# never collide with user-loaded data.
TABLE_CUSTOMERS = "demo_customers"
TABLE_ORDERS = "demo_orders"
TABLE_ORDER_ITEMS = "demo_order_items"
TABLE_PRODUCTS = "demo_products"


DATASET_NAMES = {
    TABLE_CUSTOMERS: "customers",
    TABLE_ORDERS: "orders",
    TABLE_ORDER_ITEMS: "order_items",
    TABLE_PRODUCTS: "products",
}


COUNTRIES = ["US", "DE", "FR", "GB", "NL", "ES", "IT", "CA", "JP", "AU"]
CATEGORIES = ["Audio", "Books", "Home", "Kitchen", "Outdoors", "Toys"]
STATUSES = ["placed", "paid", "shipped", "delivered", "cancelled"]


@dataclass(frozen=True)
class DemoRows:
    customers: list[dict[str, Any]]
    products: list[dict[str, Any]]
    orders: list[dict[str, Any]]
    items: list[dict[str, Any]]


def build_demo_rows(seed: int = 7) -> DemoRows:
    """Deterministic synthetic e-commerce data.

    Volumes (locked so the unit tests can assert them):
      40 customers, 25 products, 150 orders, 400 items.
    """
    rng = random.Random(seed)
    base = datetime(2026, 1, 1, 12, 0, 0)

    customers: list[dict[str, Any]] = []
    for i in range(1, 41):
        first = rng.choice(["Alex", "Bea", "Cam", "Dee", "Evan", "Fay", "Gus", "Hana", "Ivy", "Jude"])
        last = rng.choice(["Park", "Yu", "Smith", "Diaz", "Khan", "Roy", "Lee", "Adler", "Cruz", "Bauer"])
        name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}{i}@demo.local"
        country = rng.choice(COUNTRIES)
        created = base - timedelta(days=rng.randint(30, 720))
        customers.append({
            "id": i,
            "name": name,
            "email": email,
            "country": country,
            "created_at": created,
        })

    products: list[dict[str, Any]] = []
    for i in range(1, 26):
        cat = rng.choice(CATEGORIES)
        products.append({
            "id": i,
            "sku": f"SKU-{i:04d}",
            "name": f"{cat} item {i}",
            "category": cat,
            "price": Decimal(str(round(rng.uniform(5, 250), 2))),
        })

    orders: list[dict[str, Any]] = []
    for i in range(1, 151):
        cust = rng.randint(1, 40)
        status = rng.choices(STATUSES, weights=[1, 3, 4, 5, 1])[0]
        order_date = base - timedelta(days=rng.randint(0, 300), hours=rng.randint(0, 23))
        orders.append({
            "id": i,
            "customer_id": cust,
            "status": status,
            "total": Decimal("0.00"),
            "order_date": order_date,
        })

    items: list[dict[str, Any]] = []
    item_id = 1
    target_total = 400
    for o in orders:
        n = rng.randint(1, 3)
        for _ in range(n):
            if item_id > target_total:
                break
            prod = rng.choice(products)
            qty = rng.randint(1, 4)
            unit_price = prod["price"]
            items.append({
                "id": item_id,
                "order_id": o["id"],
                "product_id": prod["id"],
                "quantity": qty,
                "unit_price": unit_price,
            })
            item_id += 1
    while len(items) < target_total:
        prod = rng.choice(products)
        o = rng.choice(orders)
        items.append({
            "id": len(items) + 1,
            "order_id": o["id"],
            "product_id": prod["id"],
            "quantity": rng.randint(1, 4),
            "unit_price": prod["price"],
        })

    totals: dict[int, Decimal] = {}
    for it in items:
        totals[it["order_id"]] = totals.get(it["order_id"], Decimal("0.00")) + (
            it["unit_price"] * it["quantity"]
        )
    for o in orders:
        o["total"] = totals.get(o["id"], Decimal("0.00")).quantize(Decimal("0.01"))

    return DemoRows(customers=customers, products=products, orders=orders, items=items)


# (column_name, sql_type, frontend_type_label)
ColumnSpec = tuple[str, str, str]

SCHEMAS: dict[str, list[ColumnSpec]] = {
    TABLE_CUSTOMERS: [
        ("id", "BIGINT PRIMARY KEY", "integer"),
        ("name", "TEXT NOT NULL", "text"),
        ("email", "TEXT", "text"),
        ("country", "TEXT", "text"),
        ("created_at", "TIMESTAMP", "timestamp"),
    ],
    TABLE_PRODUCTS: [
        ("id", "BIGINT PRIMARY KEY", "integer"),
        ("sku", "TEXT UNIQUE NOT NULL", "text"),
        ("name", "TEXT NOT NULL", "text"),
        ("category", "TEXT", "text"),
        ("price", "NUMERIC(12,2)", "numeric"),
    ],
    TABLE_ORDERS: [
        ("id", "BIGINT PRIMARY KEY", "integer"),
        ("customer_id", "BIGINT NOT NULL REFERENCES public.demo_customers(id) ON DELETE CASCADE", "integer"),
        ("status", "TEXT NOT NULL", "text"),
        ("total", "NUMERIC(12,2)", "numeric"),
        ("order_date", "TIMESTAMP NOT NULL", "timestamp"),
    ],
    TABLE_ORDER_ITEMS: [
        ("id", "BIGINT PRIMARY KEY", "integer"),
        ("order_id", "BIGINT NOT NULL REFERENCES public.demo_orders(id) ON DELETE CASCADE", "integer"),
        ("product_id", "BIGINT NOT NULL REFERENCES public.demo_products(id)", "integer"),
        ("quantity", "INTEGER NOT NULL", "integer"),
        ("unit_price", "NUMERIC(12,2)", "numeric"),
    ],
}


DEMO_ONTOLOGY_YAML = f"""\
objects:
  Customer:
    table: {TABLE_CUSTOMERS}
    primary_key: id
    display_name: name
    description: A buyer in the demo store
    properties:
      id: integer
      name: text
      email: text
      country: text
      created_at: timestamp
    relationships:
      orders:
        target: Order
        type: one_to_many
        source_key: id
        target_key: customer_id
  Order:
    table: {TABLE_ORDERS}
    primary_key: id
    display_name: id
    description: A single purchase
    properties:
      id: integer
      customer_id: integer
      status: text
      total: numeric
      order_date: timestamp
    relationships:
      items:
        target: OrderItem
        type: one_to_many
        source_key: id
        target_key: order_id
  OrderItem:
    table: {TABLE_ORDER_ITEMS}
    primary_key: id
    display_name: id
    description: A line item on an order
    properties:
      id: integer
      order_id: integer
      product_id: integer
      quantity: integer
      unit_price: numeric
    relationships:
      product:
        target: Product
        type: many_to_one
        source_key: product_id
        target_key: id
  Product:
    table: {TABLE_PRODUCTS}
    primary_key: id
    display_name: name
    description: A product in the catalog
    properties:
      id: integer
      sku: text
      name: text
      category: text
      price: numeric
"""


def row_count(table: str, rows: DemoRows) -> int:
    return {
        TABLE_CUSTOMERS: len(rows.customers),
        TABLE_PRODUCTS: len(rows.products),
        TABLE_ORDERS: len(rows.orders),
        TABLE_ORDER_ITEMS: len(rows.items),
    }[table]


def rows_for(table: str, rows: DemoRows) -> list[dict[str, Any]]:
    return {
        TABLE_CUSTOMERS: rows.customers,
        TABLE_PRODUCTS: rows.products,
        TABLE_ORDERS: rows.orders,
        TABLE_ORDER_ITEMS: rows.items,
    }[table]


def sample_values(rows: list[dict[str, Any]], column: str, n: int = 3) -> list[Any]:
    """Pluck up to n distinct stringified sample values."""
    seen: list[Any] = []
    for r in rows:
        v = r.get(column)
        if v is None:
            continue
        s = _jsonable(v)
        if s in seen:
            continue
        seen.append(s)
        if len(seen) >= n:
            break
    return seen


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def ddl_create() -> list[str]:
    """Idempotent CREATE TABLE statements for the demo tables, in FK order."""
    out: list[str] = []
    for table in (TABLE_CUSTOMERS, TABLE_PRODUCTS, TABLE_ORDERS, TABLE_ORDER_ITEMS):
        cols = ", ".join(f'"{name}" {sql_type}' for name, sql_type, _ in SCHEMAS[table])
        out.append(f'CREATE TABLE IF NOT EXISTS "public"."{table}" ({cols})')
    return out


def ddl_drop() -> list[str]:
    return [
        f'DROP TABLE IF EXISTS "public"."{t}" CASCADE'
        for t in (TABLE_ORDER_ITEMS, TABLE_ORDERS, TABLE_PRODUCTS, TABLE_CUSTOMERS)
    ]
