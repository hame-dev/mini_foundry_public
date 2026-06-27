import pytest
from app.dashboards.data_binding import BindingResolutionError, build_dataset_transform_sql


def test_group_by_with_count():
    sql = build_dataset_transform_sql(
        schema="public", table="orders",
        group_by=["status"],
        metrics=[{"column": "*", "aggregation": "count", "alias": "count"}],
        where=None,
    )
    assert sql == 'SELECT "status", COUNT(*) AS "count" FROM "public"."orders" GROUP BY "status"'


def test_sum_metric():
    sql = build_dataset_transform_sql(
        schema="public", table="orders",
        group_by=["customer_id"],
        metrics=[{"column": "amount", "aggregation": "sum", "alias": "revenue"}],
        where=None,
    )
    assert sql == 'SELECT "customer_id", SUM("amount") AS "revenue" FROM "public"."orders" GROUP BY "customer_id"'


def test_no_groupby_no_metrics_selects_star():
    sql = build_dataset_transform_sql(
        schema="public", table="orders", group_by=[], metrics=[], where=None,
    )
    assert sql == 'SELECT * FROM "public"."orders"'


def test_unsafe_identifier_rejected():
    with pytest.raises(BindingResolutionError):
        build_dataset_transform_sql(
            schema="public", table='orders"; DROP TABLE x; --',
            group_by=[], metrics=[], where=None,
        )


def test_unknown_aggregation_rejected():
    with pytest.raises(BindingResolutionError):
        build_dataset_transform_sql(
            schema="public", table="orders",
            group_by=["status"],
            metrics=[{"column": "amount", "aggregation": "median", "alias": "m"}],
            where=None,
        )


def test_unsafe_column_in_group_by_rejected():
    with pytest.raises(BindingResolutionError):
        build_dataset_transform_sql(
            schema="public", table="orders",
            group_by=["status; DROP TABLE x"],
            metrics=[], where=None,
        )
