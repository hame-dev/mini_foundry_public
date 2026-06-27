import re
import uuid
from typing import Any
from sqlalchemy import select, text

from app.data.models import Dataset, Expectation


# Postgres unquoted identifier: start with letter/underscore, then letters/digits/underscore.
# We use this to defend against injection via operator-supplied column names.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str | None, kind: str) -> str:
    if not name or not _IDENT_RE.match(name):
        raise ValueError(f"invalid {kind} identifier: {name!r}")
    return name


class ExpectationFailedError(RuntimeError):
    def __init__(self, message: str, failures: list[dict[str, Any]]):
        super().__init__(message)
        self.failures = failures


def _build_check(qualified: str, exp: Expectation) -> tuple[str, dict[str, Any]] | None:
    """Return (sql, params) for the count-of-violating-rows query, or None if rule unknown."""
    col = _safe_ident(exp.column_name, "column_name")
    rule = exp.rule_type
    val = exp.rule_value

    if rule == "not_null":
        return f'SELECT COUNT(*) FROM {qualified} WHERE "{col}" IS NULL', {}
    if rule == "unique":
        return (
            f'SELECT COUNT(*) FROM (SELECT "{col}" FROM {qualified} '
            f'GROUP BY "{col}" HAVING COUNT(*) > 1) _dup',
            {},
        )
    if rule == "min":
        return f'SELECT COUNT(*) FROM {qualified} WHERE "{col}" < :val', {"val": val}
    if rule == "max":
        return f'SELECT COUNT(*) FROM {qualified} WHERE "{col}" > :val', {"val": val}
    if rule == "pattern":
        return f'SELECT COUNT(*) FROM {qualified} WHERE "{col}" !~ :val', {"val": val}
    return None


def _make_result(exp: Expectation, *, passed: bool, failed_count: int, error: str | None) -> dict[str, Any]:
    return {
        "expectation_id": str(exp.id),
        "column_name": exp.column_name,
        "rule_type": exp.rule_type,
        "rule_value": exp.rule_value,
        "severity": exp.severity,
        "passed": passed,
        "error_message": error,
        "failed_records_count": failed_count,
    }


def _qualified(dataset: Dataset) -> str:
    schema = _safe_ident(dataset.schema_name, "schema_name")
    table = _safe_ident(dataset.table_name, "table_name")
    return f'"{schema}"."{table}"'


def _finalize(results: list[dict[str, Any]], errors: list[str]) -> list[dict[str, Any]]:
    if errors:
        raise ExpectationFailedError("; ".join(errors), results)
    return results


def validate_expectations_sync(session, dataset_id: uuid.UUID) -> list[dict[str, Any]]:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise ValueError(f"Dataset {dataset_id} not found")

    expectations = session.query(Expectation).filter(Expectation.dataset_id == dataset_id).all()
    if not expectations:
        return []

    qualified = _qualified(dataset)
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for exp in expectations:
        check = _build_check(qualified, exp)
        if check is None:
            continue
        query, params = check
        try:
            failed_count = session.execute(text(query), params).scalar() or 0
        except Exception as e:
            results.append(_make_result(exp, passed=False, failed_count=0, error=f"Query execution failed: {e}"))
            if exp.severity == "error":
                errors.append(f"Expectation {exp.rule_type} on {exp.column_name} failed query execution: {e}")
            continue

        passed = failed_count == 0
        results.append(_make_result(
            exp, passed=passed, failed_count=failed_count,
            error=None if passed else f"Found {failed_count} violating records",
        ))
        if not passed and exp.severity == "error":
            errors.append(f"Expectation {exp.rule_type} on {exp.column_name} failed: found {failed_count} violating records")

    return _finalize(results, errors)


async def validate_expectations_async(session, dataset_id: uuid.UUID) -> list[dict[str, Any]]:
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise ValueError(f"Dataset {dataset_id} not found")

    q = await session.execute(select(Expectation).where(Expectation.dataset_id == dataset_id))
    expectations = list(q.scalars().all())
    if not expectations:
        return []

    qualified = _qualified(dataset)
    results: list[dict[str, Any]] = []
    errors: list[str] = []

    for exp in expectations:
        check = _build_check(qualified, exp)
        if check is None:
            continue
        query, params = check
        try:
            res_val = await session.execute(text(query), params)
            failed_count = res_val.scalar() or 0
        except Exception as e:
            results.append(_make_result(exp, passed=False, failed_count=0, error=f"Query execution failed: {e}"))
            if exp.severity == "error":
                errors.append(f"Expectation {exp.rule_type} on {exp.column_name} failed query execution: {e}")
            continue

        passed = failed_count == 0
        results.append(_make_result(
            exp, passed=passed, failed_count=failed_count,
            error=None if passed else f"Found {failed_count} violating records",
        ))
        if not passed and exp.severity == "error":
            errors.append(f"Expectation {exp.rule_type} on {exp.column_name} failed: found {failed_count} violating records")

    return _finalize(results, errors)
