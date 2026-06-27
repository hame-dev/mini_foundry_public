"""Build the AI prompt for the `ai_prompt` cell: NL → Python code."""
import json
from app.data.models import Dataset, DatasetColumn


SYSTEM_PROMPT = """You are a Python data analysis assistant for Mini Foundry.

Available packages (already installed in the sandbox):
- pandas, numpy, matplotlib, plotly, duckdb, polars, openpyxl

A function `load_table(name)` is preloaded; it returns a pandas DataFrame for
permitted datasets. There is NO network or DB access.

Rules:
- Output ONLY JSON: {"python": "...", "explanation": "..."}.
- Plot via matplotlib.pyplot; do not call plt.show().
- Use only the listed packages and the load_table helper.
- Reference only column names that appear in the provided schema.
"""


def build_messages(
    user_question: str,
    datasets: list[Dataset],
    columns_by_dataset: dict[str, list[DatasetColumn]],
) -> list[dict[str, str]]:
    schema_lines: list[str] = []
    for ds in datasets:
        cols = ", ".join(
            f"{c.name} {c.data_type or 'unknown'}" for c in columns_by_dataset.get(str(ds.id), [])
        )
        schema_lines.append(f"- {ds.name} ({cols})")

    schema_block = "\n".join(schema_lines) if schema_lines else "(no datasets available)"
    user_msg = (
        f"Permitted datasets (callable via load_table('<name>')):\n{schema_block}\n\n"
        f"User question: {user_question}\n\n"
        "Respond as JSON {python, explanation}."
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]


def parse_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"python": text, "explanation": ""}
    return {
        "python": str(data.get("python", "")).strip(),
        "explanation": str(data.get("explanation", "")),
    }
