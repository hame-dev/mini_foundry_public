"""Ontology action input validation rule engine.

Supported rule types:
  required  — field must be present and non-empty
  regex     — field value must match pattern
  range     — numeric value must be between min and max
  enum      — value must be one of the allowed list

Usage:
    errors = validate_action_input(action, payload)
    if errors:
        raise HTTPException(422, {"validation_errors": errors})
"""
from __future__ import annotations

import re
from typing import Any

from app.ontology.models import OntologyAction


def validate_action_input(action: OntologyAction, payload: dict[str, Any]) -> list[str]:
    rules = action.validation_rules or []
    errors: list[str] = []

    for rule in rules:
        prop = rule.get("property")
        rule_type = rule.get("type", "")

        if not prop:
            continue

        value = payload.get(prop)

        if rule_type == "required":
            if value is None or value == "":
                errors.append(f"'{prop}' is required")

        elif rule_type == "regex":
            pattern = rule.get("pattern", "")
            if value is not None and value != "":
                try:
                    if not re.match(pattern, str(value)):
                        errors.append(f"'{prop}' does not match required pattern: {pattern}")
                except re.error:
                    errors.append(f"'{prop}' has an invalid regex pattern configured: {pattern}")

        elif rule_type == "range":
            if value is not None and value != "":
                try:
                    num = float(value)
                    min_val = rule.get("min")
                    max_val = rule.get("max")
                    if min_val is not None and num < float(min_val):
                        errors.append(f"'{prop}' must be at least {min_val} (got {value})")
                    if max_val is not None and num > float(max_val):
                        errors.append(f"'{prop}' must be at most {max_val} (got {value})")
                except (TypeError, ValueError):
                    errors.append(f"'{prop}' must be a number (got {value!r})")

        elif rule_type == "enum":
            allowed = rule.get("values") or []
            if value is not None and value not in allowed:
                errors.append(f"'{prop}' must be one of: {', '.join(str(v) for v in allowed)} (got {value!r})")

    return errors
