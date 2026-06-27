import pytest
from app.dashboards.validation import LayoutValidationError, validate_layout


def _layout(components=None, filters=None):
    return {"version": 1, "components": components or [], "filters": filters or []}


def test_empty_layout_passes():
    validate_layout(_layout())


def test_wrong_version_rejected():
    with pytest.raises(LayoutValidationError, match="version"):
        validate_layout({"version": 2, "components": [], "filters": []})


def test_unknown_component_type_rejected():
    with pytest.raises(LayoutValidationError, match="unknown"):
        validate_layout(_layout([
            {"component_type": "rogue", "position": {"x": 0, "y": 0, "w": 4, "h": 2},
             "config": {}, "data_binding": {"type": "static", "rows": []}},
        ]))


def test_missing_required_config_rejected():
    # metric_card requires value_column
    with pytest.raises(LayoutValidationError, match="value_column"):
        validate_layout(_layout([
            {"component_type": "metric_card", "position": {"x": 0, "y": 0, "w": 3, "h": 2},
             "config": {}, "data_binding": {"type": "static", "rows": [{"v": 1}]}},
        ]))


def test_missing_position_rejected():
    with pytest.raises(LayoutValidationError, match="position"):
        validate_layout(_layout([
            {"component_type": "markdown", "config": {"text": "hi"}, "data_binding": {"type": "static", "rows": []}},
        ]))


def test_invalid_binding_type_rejected():
    with pytest.raises(LayoutValidationError, match="data_binding.type"):
        validate_layout(_layout([
            {"component_type": "table", "position": {"x": 0, "y": 0, "w": 6, "h": 4},
             "config": {}, "data_binding": {"type": "rogue"}},
        ]))


def test_binding_not_allowed_for_type_rejected():
    # markdown only allows static binding; sql_query should be rejected
    with pytest.raises(LayoutValidationError, match="not allowed"):
        validate_layout(_layout([
            {"component_type": "markdown", "position": {"x": 0, "y": 0, "w": 4, "h": 2},
             "config": {"text": "hi"},
             "data_binding": {"type": "sql_query", "sql": "SELECT 1", "dataset_ids": []}},
        ]))


def test_sql_query_missing_sql_rejected():
    with pytest.raises(LayoutValidationError, match="sql"):
        validate_layout(_layout([
            {"component_type": "table", "position": {"x": 0, "y": 0, "w": 6, "h": 4},
             "config": {},
             "data_binding": {"type": "sql_query", "sql": "  ", "dataset_ids": []}},
        ]))


def test_dataset_binding_missing_dataset_id_rejected():
    with pytest.raises(LayoutValidationError, match="dataset_id"):
        validate_layout(_layout([
            {"component_type": "bar_chart", "position": {"x": 0, "y": 0, "w": 6, "h": 4},
             "config": {"x": "status", "y": "count"},
             "data_binding": {"type": "dataset", "group_by": ["status"]}},
        ]))


def test_valid_mixed_layout_passes():
    validate_layout(_layout([
        {"id": "c1", "component_type": "metric_card",
         "position": {"x": 0, "y": 0, "w": 3, "h": 2},
         "config": {"value_column": "total", "format": "number"},
         "data_binding": {"type": "sql_query", "sql": "SELECT COUNT(*) AS total FROM t", "dataset_ids": []}},
        {"id": "c2", "component_type": "bar_chart",
         "position": {"x": 3, "y": 0, "w": 6, "h": 4},
         "config": {"x": "status", "y": ["count"]},
         "data_binding": {"type": "dataset", "dataset_id": "00000000-0000-0000-0000-000000000001",
                          "group_by": ["status"], "metrics": [{"column": "*", "aggregation": "count", "alias": "count"}]}},
        {"id": "c3", "component_type": "markdown",
         "position": {"x": 0, "y": 4, "w": 12, "h": 1},
         "config": {"text": "Notes go here"},
         "data_binding": {"type": "static", "rows": []}},
    ], [
        {"id": "f1", "type": "date_range", "target_fields": ["order_date"]},
    ]))


def test_filter_unknown_type_rejected():
    with pytest.raises(LayoutValidationError, match="filter"):
        validate_layout(_layout(filters=[
            {"id": "f1", "type": "rogue", "target_fields": []},
        ]))
