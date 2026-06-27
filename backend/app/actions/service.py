"""Resolve and validate governed action execution."""
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.ontology.models import ActionPermission, OntologyAction
from app.permissions.enforcement import effective_capabilities_for_object


def canonical_action_capability(raw: str | None) -> str:
    return {
        None: "run",
        "": "run",
        "can_run_action": "run",
        "run_action": "run",
        "can_writeback": "writeback",
        "can_run": "run",
    }.get(raw, raw.removeprefix("can_") if raw else "run")


async def user_can_run_action(
    session: AsyncSession, user: User, action: OntologyAction
) -> bool:
    canonical = canonical_action_capability(action.requires_capability)
    caps = await effective_capabilities_for_object(session, user, "ontology_action", action.id)
    if canonical in caps or "manage" in caps:
        return True

    user_id = user.id
    action_id = action.id
    role_q = await session.execute(select(UserRole.role_id).where(UserRole.user_id == user_id))
    role_ids = [r[0] for r in role_q.all()]
    subjects = [("user", user_id)] + [("role", rid) for rid in role_ids]
    for subject_type, subject_id in subjects:
        row = (await session.execute(
            select(ActionPermission).where(
                ActionPermission.action_id == action_id,
                ActionPermission.subject_type == subject_type,
                ActionPermission.subject_id == subject_id,
            )
        )).scalar_one_or_none()
        if row is not None and row.can_run:
            return True
    return False


def evaluate_preconditions(preconditions: dict[str, Any] | None, params: dict[str, Any]) -> list[str]:
    if not preconditions:
        return []
    failures: list[str] = []

    def check(rule: dict[str, Any], path: str = "precondition", *, collect: bool = True) -> tuple[bool, list[str]]:
        if "all" in rule:
            sub_failures: list[str] = []
            checks = []
            for idx, item in enumerate(rule.get("all") or []):
                ok, child_failures = check(item, f"{path}.all[{idx}]", collect=False)
                checks.append(ok)
                sub_failures.extend(child_failures)
            if collect:
                failures.extend(sub_failures)
            return all(checks), sub_failures
        if "any" in rule:
            checks = [check(item, f"{path}.any[{idx}]", collect=False)[0] for idx, item in enumerate(rule.get("any") or [])]
            ok = any(checks)
            local = [] if ok else [f"{path}: no alternatives matched"]
            if collect:
                failures.extend(local)
            return ok, local
        if "not" in rule:
            child_ok, _ = check(rule["not"], f"{path}.not", collect=False)
            ok = not child_ok
            local = [] if ok else [f"{path}: negated condition matched"]
            if collect:
                failures.extend(local)
            return ok, local

        param = rule.get("param")
        if not param:
            local = [f"{path}: missing param"]
            if collect:
                failures.extend(local)
            return False, local
        value = params.get(param)
        if "exists" in rule:
            ok = (param in params) is bool(rule["exists"])
        elif "equals" in rule:
            ok = value == rule["equals"]
        elif "not_equals" in rule:
            ok = value != rule["not_equals"]
        elif "in" in rule:
            allowed = rule["in"]
            ok = isinstance(allowed, list) and value in allowed
        else:
            local = [f"{path}: unsupported operator"]
            if collect:
                failures.extend(local)
            return False, local
        if not ok:
            local = [f"{path}: {param} did not satisfy precondition"]
            if collect:
                failures.extend(local)
            return False, local
        return True, []

    check(preconditions)
    return failures
