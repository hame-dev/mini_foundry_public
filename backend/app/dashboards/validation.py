"""Layout validation. Raise LayoutValidationError with a precise path on
the first failure. Used on PUT /dashboards/{id} and on AI-generated layouts.
"""
from typing import Any

from app.dashboards.registry import ALL_BINDINGS, COMPONENTS, spec_for


class LayoutValidationError(ValueError):
    pass


def _check_type(value: Any, expected: Any, path: str) -> None:
    if isinstance(expected, set):
        if value not in expected:
            raise LayoutValidationError(f"{path}: must be one of {sorted(expected)}, got {value!r}")
        return
    if isinstance(expected, tuple):
        if not isinstance(value, expected):
            names = "|".join(t.__name__ for t in expected)
            raise LayoutValidationError(f"{path}: expected {names}, got {type(value).__name__}")
        return
    if not isinstance(value, expected):
        raise LayoutValidationError(f"{path}: expected {expected.__name__}, got {type(value).__name__}")


def validate_component(component: dict, index: int) -> None:
    path = f"components[{index}]"
    if not isinstance(component, dict):
        raise LayoutValidationError(f"{path}: must be an object")

    ctype = component.get("component_type")
    spec = spec_for(ctype) if isinstance(ctype, str) else None
    if spec is None:
        raise LayoutValidationError(
            f"{path}.component_type: unknown {ctype!r}; allowed = {sorted(COMPONENTS.keys())}"
        )

    pos = component.get("position")
    if not isinstance(pos, dict) or not all(isinstance(pos.get(k), int) for k in ("x", "y", "w", "h")):
        raise LayoutValidationError(f"{path}.position: must be {{x:int, y:int, w:int, h:int}}")

    config = component.get("config", {})
    if not isinstance(config, dict):
        raise LayoutValidationError(f"{path}.config: must be an object")

    for key, expected in spec["required"].items():
        if key not in config:
            raise LayoutValidationError(f"{path}.config.{key}: required")
        _check_type(config[key], expected, f"{path}.config.{key}")

    for key, expected in spec["optional"].items():
        if key in config:
            _check_type(config[key], expected, f"{path}.config.{key}")

    binding = component.get("data_binding")
    if binding is not None:
        if not isinstance(binding, dict):
            raise LayoutValidationError(f"{path}.data_binding: must be an object")
        btype = binding.get("type")
        if btype not in ALL_BINDINGS:
            raise LayoutValidationError(
                f"{path}.data_binding.type: must be one of {sorted(ALL_BINDINGS)}, got {btype!r}"
            )
        if btype not in spec["bindings"]:
            raise LayoutValidationError(
                f"{path}.data_binding.type: {btype!r} not allowed for {ctype}; allowed = {sorted(spec['bindings'])}"
            )
        _validate_binding_shape(binding, f"{path}.data_binding")
    elif spec["bindings"] != {"static"}:
        # static-only components may omit binding; everything else needs one
        raise LayoutValidationError(f"{path}.data_binding: required for component {ctype}")

    # v0.7: actions[] (optional)
    actions = component.get("actions")
    if actions is not None:
        if not isinstance(actions, list):
            raise LayoutValidationError(f"{path}.actions: must be a list")
        for i, action in enumerate(actions):
            _validate_action(action, f"{path}.actions[{i}]")


ACTION_TYPES = {"open_object", "filter", "navigate", "run_workflow"}
ACTION_EVENTS = {"on_row_click", "on_click", "on_cell_click"}


def _validate_action(action: dict, path: str) -> None:
    if not isinstance(action, dict):
        raise LayoutValidationError(f"{path}: must be an object")
    event = action.get("event")
    if event not in ACTION_EVENTS:
        raise LayoutValidationError(f"{path}.event: must be one of {sorted(ACTION_EVENTS)}")
    atype = action.get("type")
    if atype not in ACTION_TYPES:
        raise LayoutValidationError(f"{path}.type: must be one of {sorted(ACTION_TYPES)}")

    if atype == "open_object":
        for key in ("object_type", "id_field"):
            if not isinstance(action.get(key), str):
                raise LayoutValidationError(f"{path}.{key}: required string")
    elif atype == "filter":
        if not isinstance(action.get("filter_id"), str):
            raise LayoutValidationError(f"{path}.filter_id: required string")
        if "source_field" in action and not isinstance(action["source_field"], str):
            raise LayoutValidationError(f"{path}.source_field: must be string")
    elif atype == "navigate":
        if not isinstance(action.get("to"), str):
            raise LayoutValidationError(f"{path}.to: required URL/path string")
    elif atype == "run_workflow":
        if not isinstance(action.get("action_name"), str):
            raise LayoutValidationError(f"{path}.action_name: required string")


def _validate_binding_shape(binding: dict, path: str) -> None:
    btype = binding["type"]
    if btype == "sql_query":
        if not isinstance(binding.get("sql"), str) or not binding["sql"].strip():
            raise LayoutValidationError(f"{path}.sql: required non-empty string")
        dataset_ids = binding.get("dataset_ids", [])
        if not isinstance(dataset_ids, list) or not all(isinstance(x, str) for x in dataset_ids):
            raise LayoutValidationError(f"{path}.dataset_ids: must be a list of UUID strings")
    elif btype == "dataset":
        if not isinstance(binding.get("dataset_id"), str):
            raise LayoutValidationError(f"{path}.dataset_id: required UUID string")
        for key in ("group_by", "metrics"):
            if key in binding and not isinstance(binding[key], list):
                raise LayoutValidationError(f"{path}.{key}: must be a list")
    elif btype == "static":
        rows = binding.get("rows", [])
        if not isinstance(rows, list):
            raise LayoutValidationError(f"{path}.rows: must be a list")
    elif btype == "saved_query":
        if not isinstance(binding.get("id"), str):
            raise LayoutValidationError(f"{path}.id: required saved_query UUID")


def validate_filter(f: dict, index: int) -> None:
    path = f"filters[{index}]"
    if not isinstance(f, dict):
        raise LayoutValidationError(f"{path}: must be an object")
    if not isinstance(f.get("id"), str):
        raise LayoutValidationError(f"{path}.id: required string")
    if f.get("type") not in {"date_range", "select", "multi_select", "search"}:
        raise LayoutValidationError(f"{path}.type: unknown filter type {f.get('type')!r}")
    if not isinstance(f.get("target_fields", []), list):
        raise LayoutValidationError(f"{path}.target_fields: must be a list")


def validate_layout(layout: dict) -> None:
    if not isinstance(layout, dict):
        raise LayoutValidationError("layout: must be an object")
    if layout.get("version") != 1:
        raise LayoutValidationError("layout.version: must be 1")
    components = layout.get("components", [])
    if not isinstance(components, list):
        raise LayoutValidationError("layout.components: must be a list")
    for i, c in enumerate(components):
        validate_component(c, i)
    filters = layout.get("filters", [])
    if not isinstance(filters, list):
        raise LayoutValidationError("layout.filters: must be a list")
    for i, f in enumerate(filters):
        validate_filter(f, i)
