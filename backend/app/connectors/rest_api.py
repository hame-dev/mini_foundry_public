"""REST API connector with page, offset, cursor, link, and watermark support.
"""
import re
import uuid
from typing import Any
from urllib.parse import urljoin

import httpx
import pandas as pd
from sqlalchemy import create_engine, text

from app.config import get_settings

DATASET_SCHEMA = "mf_datasets"


def _safe_table_name(base: str, dataset_id: uuid.UUID) -> str:
    base = re.sub(r"[^a-z0-9_]", "_", base.lower())[:32].strip("_") or "api"
    return f"staging_{base}_{dataset_id.hex[:8]}"


def _build_headers(auth: dict[str, Any] | None, extra: dict[str, str] | None) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if auth:
        kind = auth.get("type")
        if kind == "bearer_token":
            headers["Authorization"] = f"Bearer {auth['token']}"
        elif kind == "api_key_header":
            headers[auth["header_name"]] = auth["token"]
    if extra:
        headers.update(extra)
    return headers


def _extract_records(data: Any, response_path: str | None) -> list[dict]:
    if response_path:
        # very small JSONPath subset: "$.data" / "$.items"
        keys = [k for k in response_path.replace("$.", "").split(".") if k]
        node = data
        for k in keys:
            node = node[k]
        data = node
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def fetch_rest_endpoint(config: dict[str, Any], dataset_name: str, dataset_id: uuid.UUID) -> dict[str, Any]:
    """Run a paginated GET and write rows to a staging table.

    Expected config:
      {
        "base_url": "...",
        "path": "/orders",
        "auth": {"type": "bearer_token", "token": "..."} | null,
        "headers": {...} | null,
        "params": {...} | null,
        "pagination": {"type": "page|offset|cursor|link", ...} | null,
        "watermark": {"param": "updated_after", "value": "...", "field": "updated_at"} | null,
        "response_path": "$.data" | null
      }
    """
    base_url = config["base_url"].rstrip("/")
    path = config.get("path", "/")
    headers = _build_headers(config.get("auth"), config.get("headers"))
    base_params: dict[str, Any] = dict(config.get("params") or {})
    pag = config.get("pagination") or {}
    page_param = pag.get("page_param", "page")
    size_param = pag.get("page_size_param", "limit")
    page_size = pag.get("page_size", 100)
    max_pages = pag.get("max_pages", 10)
    response_path = config.get("response_path")
    watermark = config.get("watermark") or {}
    if watermark.get("param") and watermark.get("value") is not None:
        base_params[watermark["param"]] = watermark["value"]

    rows: list[dict] = []
    next_cursor = pag.get("cursor")
    next_url: str | None = None
    with httpx.Client(timeout=30.0) as client:
        for page_index in range(max_pages):
            params = dict(base_params)
            pagination_type = pag.get("type")
            url = next_url or f"{base_url}{path}"
            if pagination_type == "page":
                params[page_param] = page_index + 1
                params[size_param] = page_size
            elif pagination_type == "offset":
                params[pag.get("offset_param", "offset")] = int(pag.get("start_offset", 0)) + page_index * int(page_size)
                params[size_param] = page_size
            elif pagination_type == "cursor" and next_cursor:
                params[pag.get("cursor_param", "cursor")] = next_cursor
                params[size_param] = page_size
            resp = client.get(url, params=params if not next_url else None, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            batch = _extract_records(body, response_path)
            if not batch:
                break
            rows.extend(batch)
            if pagination_type == "cursor":
                cursor_path = pag.get("next_cursor_path", "$.next_cursor")
                try:
                    node: Any = body
                    for key in [k for k in cursor_path.replace("$.", "").split(".") if k]:
                        node = node[key]
                    next_cursor = str(node) if node else None
                except Exception:
                    next_cursor = None
                if not next_cursor:
                    break
            elif pagination_type == "link":
                link = resp.links.get("next", {}).get("url")
                next_url = urljoin(base_url, link) if link else None
                if not next_url:
                    break
            elif pagination_type not in {"page", "offset"} or len(batch) < page_size:
                break

    df = pd.DataFrame(rows)
    table = _safe_table_name(dataset_name, dataset_id)
    engine = create_engine(get_settings().sync_database_url)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{DATASET_SCHEMA}"'))
    df.to_sql(table, engine, schema=DATASET_SCHEMA, if_exists="replace", index=False)

    columns = [
        {"name": str(c), "type": str(df[c].dtype), "sample": df[c].dropna().head(3).tolist()}
        for c in df.columns
    ]
    high_water_mark = None
    watermark_field = watermark.get("field")
    if watermark_field and watermark_field in df.columns and not df.empty:
        high_water_mark = str(df[watermark_field].max())
    return {"schema_name": DATASET_SCHEMA, "table_name": table, "row_count": int(len(df)), "columns": columns, "high_water_mark": high_water_mark}
