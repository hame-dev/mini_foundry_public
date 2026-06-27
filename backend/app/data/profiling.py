"""Lightweight profiling that runs against the mini_foundry DB itself.

For external Postgres sources, we'd query through their engine; for now we
profile staging tables we own (CSV/REST imports).
"""
import re
import json
from typing import Any
from sqlalchemy import create_engine, text

from app.config import get_settings


def profile_local_table(schema: str, table: str) -> dict[str, Any]:
    engine = create_engine(get_settings().sync_database_url)
    with engine.connect() as conn:
        count = conn.execute(text(f'SELECT COUNT(*) FROM "{schema}"."{table}"')).scalar() or 0
        cols_q = conn.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"
            ),
            {"s": schema, "t": table},
        )
        columns: dict[str, dict] = {}
        for name, dtype in cols_q.all():
            quoted = f'"{schema}"."{table}"'
            col = f'"{name}"'
            null_count = 0
            null_pct = 0.0
            if count > 0:
                nulls = conn.execute(
                    text(f"SELECT COUNT(*) FROM {quoted} WHERE {col} IS NULL")
                ).scalar() or 0
                null_count = int(nulls)
                null_pct = round(nulls / count, 4)
            distinct_count = conn.execute(text(f"SELECT COUNT(DISTINCT {col}) FROM {quoted}")).scalar() or 0
            samples = [
                r[0]
                for r in conn.execute(text(f"SELECT {col} FROM {quoted} WHERE {col} IS NOT NULL LIMIT 25")).all()
            ]
            min_val = max_val = None
            if dtype in {"integer", "bigint", "numeric", "double precision", "real", "date", "timestamp without time zone", "timestamp with time zone"}:
                try:
                    min_val, max_val = conn.execute(text(f"SELECT MIN({col}), MAX({col}) FROM {quoted}")).one()
                except Exception:
                    pass
            classifications = classify_column(name, samples)
            columns[name] = {
                "type": dtype,
                "null_count": null_count,
                "null_percent": null_pct,
                "distinct_count": int(distinct_count),
                "min": str(min_val) if min_val is not None else None,
                "max": str(max_val) if max_val is not None else None,
                "classifications": classifications,
                "sensitivity": sensitivity_for_classifications(classifications),
                "suggested_markings": suggested_markings_for_classifications(classifications),
                "common_values_sample": [str(v) for v in samples[:10]],
            }
    dataset_markings = sorted({mark for c in columns.values() for mark in c.get("suggested_markings", [])})
    return {"row_count": int(count), "columns": columns, "quality_status": "profiled", "suggested_markings": dataset_markings}


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9\-\s().]{7,}$")
FINANCIAL_RE = re.compile(r"^(?:[0-9]{13,19}|[A-Z]{2}[0-9A-Z]{13,32})$")


def classify_column(name: str, samples: list[Any]) -> list[str]:
    labels: set[str] = set()
    lower = name.lower()
    if any(token in lower for token in ("email", "e_mail")):
        labels.add("pii.email")
    if any(token in lower for token in ("phone", "mobile", "tel")):
        labels.add("pii.phone")
    if any(token in lower for token in ("address", "city", "country", "lat", "lon", "location")):
        labels.add("pii.location")
    if any(token in lower for token in ("card", "iban", "account", "routing")):
        labels.add("financial.identifier")
    sample_strings = [str(v) for v in samples if v is not None]
    if sample_strings and sum(bool(EMAIL_RE.match(v)) for v in sample_strings) >= max(1, len(sample_strings) // 2):
        labels.add("pii.email")
    if sample_strings and sum(bool(PHONE_RE.match(v)) for v in sample_strings) >= max(1, len(sample_strings) // 2):
        labels.add("pii.phone")
    if sample_strings and sum(bool(FINANCIAL_RE.match(v.replace(" ", ""))) for v in sample_strings) >= max(1, len(sample_strings) // 2):
        labels.add("financial.identifier")
    for rule in custom_regex_rules():
        pattern = rule.get("pattern")
        label = rule.get("label")
        if not pattern or not label:
            continue
        try:
            regex = re.compile(str(pattern))
        except re.error:
            continue
        if regex.search(name) or (sample_strings and sum(bool(regex.search(v)) for v in sample_strings) >= max(1, len(sample_strings) // 2)):
            labels.add(str(label))
    return sorted(labels)


def custom_regex_rules() -> list[dict[str, Any]]:
    raw = get_settings().custom_regex_classifiers
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def sensitivity_for_classifications(classifications: list[str]) -> str:
    labels = set(classifications)
    if any(label.startswith("financial.") for label in labels):
        return "restricted"
    if any(label.startswith("pii.") for label in labels):
        return "confidential"
    return "internal"


def suggested_markings_for_classifications(classifications: list[str]) -> list[str]:
    markings: set[str] = set()
    for label in classifications:
        if label.startswith("pii."):
            markings.add("PII")
        if label.startswith("financial."):
            markings.add("FINANCIAL")
    for rule in custom_regex_rules():
        if rule.get("label") in classifications and rule.get("marking"):
            markings.add(str(rule["marking"]))
    return sorted(markings)
