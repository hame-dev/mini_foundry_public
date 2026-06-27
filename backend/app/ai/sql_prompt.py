"""Builds the schema-aware SQL prompt described in README §7."""
import json
from app.data.models import Dataset, DatasetColumn


SYSTEM_PROMPT = """You are a SQL generator for Mini Foundry.

Rules:
- Output ONLY a single PostgreSQL SELECT statement (no DDL, DML, or multi-statement).
- Use only the tables and columns provided in the schema.
- Always include a LIMIT clause (max 1000).
- Reply as JSON: {"sql": "...", "explanation": "...", "confidence": 0.0-1.0}.
"""


def build_messages(
    user_question: str,
    datasets: list[Dataset],
    columns_by_dataset: dict[str, list[DatasetColumn]],
) -> list[dict[str, str]]:
    schema_lines: list[str] = []
    for ds in datasets:
        col_strs = ", ".join(
            f"{c.name} {c.data_type or 'unknown'}" for c in columns_by_dataset.get(str(ds.id), [])
        )
        schema_lines.append(f'- "{ds.schema_name}"."{ds.table_name}" ({col_strs})')
        if ds.description:
            schema_lines.append(f"    description: {ds.description}")

    schema_block = "\n".join(schema_lines) if schema_lines else "(no datasets available)"

    user_msg = (
        f"Schema (only these tables/columns are valid):\n{schema_block}\n\n"
        f"Question: {user_question}\n\n"
        "Respond as JSON with keys: sql, explanation, confidence."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]


def parse_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        # strip possible ```json ... ``` fences
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Best-effort: treat as raw SQL
        return {"sql": text, "explanation": "", "confidence": 0.0}
    return {
        "sql": str(data.get("sql", "")).strip(),
        "explanation": str(data.get("explanation", "")),
        "confidence": float(data.get("confidence", 0.0) or 0.0),
    }
