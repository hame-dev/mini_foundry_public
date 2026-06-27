"""Workflow registry.

User-defined workflows live as @workflow-decorated functions in any module
under app.actions.workflows_user; they get imported at app startup via
`load_user_workflows()`.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Callable


WORKFLOWS: dict[str, dict[str, Any]] = {}


def workflow(name: str, *, sync: bool = True):
    """Register a workflow.

    Signature contract: fn(session, user, params) -> dict | None.
    sync=False enqueues a Celery job instead of running inline.
    """
    def deco(fn: Callable) -> Callable:
        WORKFLOWS[name] = {"fn": fn, "sync": sync}
        return fn
    return deco


def get_workflow(name: str) -> dict[str, Any]:
    if name not in WORKFLOWS:
        raise KeyError(f"unknown workflow: {name}")
    return WORKFLOWS[name]


def list_workflows() -> list[dict[str, Any]]:
    return [{"name": k, "sync": v["sync"]} for k, v in sorted(WORKFLOWS.items())]


def load_user_workflows() -> None:
    """Walk `app.actions.workflows_user` and import every submodule so its
    @workflow decorators run."""
    try:
        pkg = importlib.import_module("app.actions.workflows_user")
    except ImportError:
        return
    if not hasattr(pkg, "__path__"):
        return
    for _, mod_name, _ in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        importlib.import_module(mod_name)


def validate_params(input_schema: dict | None, params: dict) -> None:
    """Tiny JSONSchema-style validator. Supports `required` list and a
    `properties` map of {key: {type: "string|number|boolean|uuid"}}."""
    if not input_schema:
        return
    required = input_schema.get("required", [])
    for key in required:
        if key not in params:
            raise ValueError(f"missing required param: {key}")
    props = input_schema.get("properties", {})
    for key, spec in props.items():
        if key not in params:
            continue
        t = spec.get("type")
        v = params[key]
        if t == "string" and not isinstance(v, str):
            raise ValueError(f"{key}: expected string")
        elif t == "number" and not isinstance(v, (int, float)):
            raise ValueError(f"{key}: expected number")
        elif t == "boolean" and not isinstance(v, bool):
            raise ValueError(f"{key}: expected boolean")
        elif t == "uuid":
            import uuid as _u
            if not isinstance(v, str):
                raise ValueError(f"{key}: expected uuid string")
            try:
                _u.UUID(v)
            except ValueError:
                raise ValueError(f"{key}: invalid uuid")
