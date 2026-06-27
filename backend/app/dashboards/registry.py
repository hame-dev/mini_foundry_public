"""Component registry: declares every component type allowed on a dashboard,
its accepted binding types, and the schema of its `config` payload.

`required` keys must be present and match `type`. `optional` keys may be
absent; if present they must match `type`. Enum values are expressed as
sets; any other value means "must be an instance of this Python type".
"""
from typing import Any


# Binding type tokens
BINDING_SQL_QUERY = "sql_query"
BINDING_DATASET = "dataset"
BINDING_STATIC = "static"
BINDING_SAVED_QUERY = "saved_query"
ALL_BINDINGS = {BINDING_SQL_QUERY, BINDING_DATASET, BINDING_STATIC, BINDING_SAVED_QUERY}


COMPONENTS: dict[str, dict[str, Any]] = {
    "metric_card": {
        "bindings": {BINDING_SQL_QUERY, BINDING_DATASET, BINDING_STATIC, BINDING_SAVED_QUERY},
        "required": {"value_column": str},
        "optional": {"format": {"currency", "number", "percent"}, "label": str},
    },
    "table": {
        "bindings": {BINDING_SQL_QUERY, BINDING_DATASET, BINDING_SAVED_QUERY},
        "required": {},
        "optional": {"columns": list, "page_size": int},
    },
    "line_chart": {
        "bindings": {BINDING_SQL_QUERY, BINDING_DATASET, BINDING_SAVED_QUERY},
        "required": {"x": str, "y": (str, list)},
        "optional": {"format": str},
    },
    "bar_chart": {
        "bindings": {BINDING_SQL_QUERY, BINDING_DATASET, BINDING_SAVED_QUERY},
        "required": {"x": str, "y": (str, list)},
        "optional": {"stacked": bool},
    },
    "pie_chart": {
        "bindings": {BINDING_SQL_QUERY, BINDING_DATASET, BINDING_SAVED_QUERY},
        "required": {"label": str, "value": str},
        "optional": {},
    },
    "markdown": {
        "bindings": {BINDING_STATIC},
        "required": {"text": str},
        "optional": {},
    },
    "filter_date": {
        "bindings": {BINDING_STATIC},
        "required": {"target_fields": list},
        "optional": {"default_range_days": int},
    },
    "filter_select": {
        "bindings": {BINDING_SQL_QUERY, BINDING_DATASET, BINDING_STATIC, BINDING_SAVED_QUERY},
        "required": {"target_field": str, "value_column": str},
        "optional": {"multi": bool, "label_column": str},
    },
    "object_table": {
        "bindings": {BINDING_STATIC, BINDING_DATASET, BINDING_SQL_QUERY, BINDING_SAVED_QUERY},
        "required": {},
        "optional": {"object_type": str, "columns": list},
    },
    "button_group": {
        "bindings": {BINDING_STATIC},
        "required": {"buttons": list},
        "optional": {},
    },
    "filter_list": {
        "bindings": {BINDING_STATIC, BINDING_DATASET, BINDING_SQL_QUERY, BINDING_SAVED_QUERY},
        "required": {},
        "optional": {"target_field": str},
    },
    "chart_xy": {
        "bindings": {BINDING_SQL_QUERY, BINDING_DATASET, BINDING_SAVED_QUERY},
        "required": {"x": str, "y": (str, list)},
        "optional": {"mark": str},
    },
    "map": {
        "bindings": {BINDING_STATIC, BINDING_DATASET, BINDING_SQL_QUERY, BINDING_SAVED_QUERY},
        "required": {},
        "optional": {"latitude": str, "longitude": str},
    },
    "data_table": {
        "bindings": {BINDING_SQL_QUERY, BINDING_DATASET, BINDING_SAVED_QUERY},
        "required": {},
        "optional": {"columns": list, "page_size": int},
    },
}


def known_component_types() -> list[str]:
    return sorted(COMPONENTS.keys())


def spec_for(component_type: str) -> dict[str, Any] | None:
    return COMPONENTS.get(component_type)
