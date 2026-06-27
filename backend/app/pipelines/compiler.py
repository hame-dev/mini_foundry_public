"""Compile a pipeline graph to a single read-only SQL statement.

Each non-source node becomes a CTE that selects from its predecessor(s).
Identifiers are quoted; user-supplied SQL fragments (filter ``where``,
formula ``expr``) are validated by parsing them as part of the compiled
statement via ``validate_sql`` in the caller.

We deliberately produce a single SELECT-with-CTEs so the existing
``run_sql`` path can execute and ``CREATE OR REPLACE VIEW`` can wrap it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import UUID


class PipelineCompileError(ValueError):
    pass


# --- input shape (plain dicts, taken from the API layer) --------------------

# A node dict:
#   { "id": str, "node_type": NodeType, "config": {...} }
# An edge dict:
#   { "id": str, "source_node_id": str, "target_node_id": str,
#     "target_handle": "left" | "right" | "in" }


@dataclass
class CompiledPipeline:
    sql: str
    output_columns: list[str]
    dataset_ids: list[UUID]
    output_node_id: str
    output_name: str
    output_description: str | None = None


@dataclass
class _NodeView:
    """Bookkeeping for a single CTE: its alias + the columns it exposes."""

    cte_alias: str
    columns: list[str] = field(default_factory=list)


def _quote_ident(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise PipelineCompileError("identifier must be a non-empty string")
    if '"' in name:
        raise PipelineCompileError(f"identifier may not contain double-quote: {name!r}")
    return f'"{name}"'


def _safe_alias(prefix: str, node_id: str) -> str:
    # Keep CTE aliases stable + safe; strip non-alphanum.
    cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in node_id)
    return f"{prefix}_{cleaned}"[:63]


def _dataset_lookup(datasets: Iterable[Any]) -> dict[UUID, Any]:
    out: dict[UUID, Any] = {}
    for d in datasets:
        out[d.id] = d
    return out


def _columns_of(dataset: Any, dataset_columns_by_id: dict[UUID, list[Any]]) -> list[str]:
    cols = dataset_columns_by_id.get(dataset.id, [])
    return [c.name for c in cols]


def _topo_order(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Kahn's algorithm. Raises on cycles or unknown ids."""
    by_id = {n["id"]: n for n in nodes}
    in_deg = {n["id"]: 0 for n in nodes}
    out_edges: dict[str, list[str]] = {n["id"]: [] for n in nodes}

    for e in edges:
        s, t = e["source_node_id"], e["target_node_id"]
        if s not in by_id or t not in by_id:
            raise PipelineCompileError(f"edge references unknown node: {s} -> {t}")
        in_deg[t] += 1
        out_edges[s].append(t)

    queue = [nid for nid, d in in_deg.items() if d == 0]
    ordered: list[str] = []
    while queue:
        # deterministic order by node id
        queue.sort()
        nid = queue.pop(0)
        ordered.append(nid)
        for nxt in out_edges[nid]:
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(nodes):
        raise PipelineCompileError("graph has a cycle")
    return ordered


def _predecessors(node_id: str, edges: list[dict]) -> list[dict]:
    return [e for e in edges if e["target_node_id"] == node_id]


def compile_pipeline(
    *,
    nodes: list[dict],
    edges: list[dict],
    datasets: list[Any],
    dataset_columns_by_id: dict[UUID, list[Any]],
) -> CompiledPipeline:
    """Compile a graph to a read-only SQL statement.

    ``datasets`` and ``dataset_columns_by_id`` are pre-loaded by the caller
    so the compiler stays pure / synchronous and easy to test.
    """
    if not nodes:
        raise PipelineCompileError("pipeline is empty")

    # Resolve the single output node.
    output_nodes = [n for n in nodes if n["node_type"] == "output"]
    if len(output_nodes) != 1:
        raise PipelineCompileError("pipeline must have exactly one output node")
    output_node = output_nodes[0]

    by_id = {n["id"]: n for n in nodes}
    order = _topo_order(nodes, edges)
    ds_by_id = _dataset_lookup(datasets)

    views: dict[str, _NodeView] = {}
    ctes: list[str] = []
    referenced_dataset_ids: list[UUID] = []

    for nid in order:
        node = by_id[nid]
        ntype = node["node_type"]
        cfg = node.get("config") or {}
        preds = _predecessors(nid, edges)
        cte_alias = _safe_alias("n", nid)

        if ntype == "source":
            ds_id = cfg.get("dataset_id")
            if not ds_id:
                raise PipelineCompileError(f"source node {nid} missing dataset_id")
            try:
                ds_uuid = UUID(str(ds_id))
            except ValueError as e:
                raise PipelineCompileError(f"invalid dataset_id on source {nid}: {ds_id}") from e
            ds = ds_by_id.get(ds_uuid)
            if ds is None:
                raise PipelineCompileError(f"source dataset not found: {ds_id}")
            referenced_dataset_ids.append(ds_uuid)
            cols = _columns_of(ds, dataset_columns_by_id)
            if not cols:
                # Allow a source with unknown schema (use SELECT * downstream).
                col_list = "*"
            else:
                col_list = ", ".join(_quote_ident(c) for c in cols)
            sql = (
                f"SELECT {col_list} FROM {_quote_ident(ds.schema_name)}."
                f"{_quote_ident(ds.table_name)}"
            )
            ctes.append(f"{cte_alias} AS (\n  {sql}\n)")
            views[nid] = _NodeView(cte_alias=cte_alias, columns=list(cols))
            continue

        if ntype == "filter":
            if len(preds) != 1:
                raise PipelineCompileError(f"filter node {nid} requires exactly one input")
            up = views[preds[0]["source_node_id"]]
            where = (cfg.get("where") or "").strip()
            if not where:
                # No-op filter — passthrough.
                inner = f"SELECT * FROM {up.cte_alias}"
            else:
                inner = f"SELECT * FROM {up.cte_alias} WHERE {where}"
            ctes.append(f"{cte_alias} AS (\n  {inner}\n)")
            views[nid] = _NodeView(cte_alias=cte_alias, columns=list(up.columns))
            continue

        if ntype == "select":
            if len(preds) != 1:
                raise PipelineCompileError(f"select node {nid} requires exactly one input")
            up = views[preds[0]["source_node_id"]]
            chosen: list[str] = list(cfg.get("columns") or []) or list(up.columns)
            rename: dict[str, str] = cfg.get("rename") or {}
            parts: list[str] = []
            new_cols: list[str] = []
            for c in chosen:
                if up.columns and c not in up.columns:
                    raise PipelineCompileError(
                        f"select node {nid} references unknown column {c!r}"
                    )
                if c in rename and rename[c]:
                    parts.append(f"{_quote_ident(c)} AS {_quote_ident(rename[c])}")
                    new_cols.append(rename[c])
                else:
                    parts.append(_quote_ident(c))
                    new_cols.append(c)
            inner = f"SELECT {', '.join(parts) if parts else '*'} FROM {up.cte_alias}"
            ctes.append(f"{cte_alias} AS (\n  {inner}\n)")
            views[nid] = _NodeView(cte_alias=cte_alias, columns=new_cols)
            continue

        if ntype == "formula":
            if len(preds) != 1:
                raise PipelineCompileError(f"formula node {nid} requires exactly one input")
            up = views[preds[0]["source_node_id"]]
            formula_cols = cfg.get("columns") or []
            extras: list[str] = []
            new_col_names: list[str] = list(up.columns)
            for fc in formula_cols:
                name = (fc.get("name") or "").strip()
                expr = (fc.get("expr") or "").strip()
                if not name or not expr:
                    raise PipelineCompileError(f"formula in {nid} requires name and expr")
                extras.append(f"({expr}) AS {_quote_ident(name)}")
                new_col_names.append(name)
            base = "*"
            inner = f"SELECT {base}{(', ' + ', '.join(extras)) if extras else ''} FROM {up.cte_alias}"
            ctes.append(f"{cte_alias} AS (\n  {inner}\n)")
            views[nid] = _NodeView(cte_alias=cte_alias, columns=new_col_names)
            continue

        if ntype == "union":
            if len(preds) < 2:
                raise PipelineCompileError(f"union node {nid} requires at least 2 inputs")
            distinct = bool(cfg.get("distinct"))
            joiner = "\nUNION\n" if distinct else "\nUNION ALL\n"
            pieces = [f"SELECT * FROM {views[p['source_node_id']].cte_alias}" for p in preds]
            inner = joiner.join(pieces)
            # Column shape = first input's columns (we trust the user to align).
            first_cols = views[preds[0]["source_node_id"]].columns
            ctes.append(f"{cte_alias} AS (\n  {inner}\n)")
            views[nid] = _NodeView(cte_alias=cte_alias, columns=list(first_cols))
            continue

        if ntype == "trained_model":
            if len(preds) != 1:
                raise PipelineCompileError(f"trained_model node {nid} requires exactly one input")
            up = views[preds[0]["source_node_id"]]
            pred_col = (cfg.get("prediction_column") or "prediction").strip()
            if not pred_col:
                raise PipelineCompileError(f"trained_model node {nid} requires prediction_column")
            # v1 exposes the prediction contract as a SQL materialized column. The
            # model artifact/version is tracked in node config for lineage and UI.
            inner = f"SELECT *, NULL::double precision AS {_quote_ident(pred_col)} FROM {up.cte_alias}"
            ctes.append(f"{cte_alias} AS (\n  {inner}\n)")
            views[nid] = _NodeView(cte_alias=cte_alias, columns=[*up.columns, pred_col])
            continue

        if ntype == "join":
            left_pred = next((p for p in preds if p["target_handle"] == "left"), None)
            right_pred = next((p for p in preds if p["target_handle"] == "right"), None)
            if left_pred is None or right_pred is None:
                raise PipelineCompileError(
                    f"join node {nid} requires both 'left' and 'right' inputs"
                )
            left = views[left_pred["source_node_id"]]
            right = views[right_pred["source_node_id"]]
            join_type = (cfg.get("join_type") or "inner").upper()
            if join_type not in {"INNER", "LEFT", "RIGHT", "FULL"}:
                raise PipelineCompileError(f"invalid join_type: {join_type}")
            left_keys = cfg.get("left_keys") or []
            right_keys = cfg.get("right_keys") or []
            if not left_keys or not right_keys or len(left_keys) != len(right_keys):
                raise PipelineCompileError(
                    f"join node {nid} requires matching left_keys and right_keys"
                )
            # Alias inputs to avoid duplicate column collisions in the CTE columns list.
            la, ra = "l", "r"
            on_parts = [
                f"{la}.{_quote_ident(lk)} = {ra}.{_quote_ident(rk)}"
                for lk, rk in zip(left_keys, right_keys)
            ]
            # Build a column list, preferring left then suffixing duplicates from right.
            seen: set[str] = set()
            cols_select: list[str] = []
            out_cols: list[str] = []
            for c in left.columns:
                cols_select.append(f"{la}.{_quote_ident(c)}")
                out_cols.append(c)
                seen.add(c)
            for c in right.columns:
                if c in seen:
                    new = f"{c}_r"
                    cols_select.append(f"{ra}.{_quote_ident(c)} AS {_quote_ident(new)}")
                    out_cols.append(new)
                else:
                    cols_select.append(f"{ra}.{_quote_ident(c)}")
                    out_cols.append(c)
                    seen.add(c)
            select_clause = ", ".join(cols_select) if cols_select else "*"
            inner = (
                f"SELECT {select_clause} FROM {left.cte_alias} {la} "
                f"{join_type} JOIN {right.cte_alias} {ra} ON {' AND '.join(on_parts)}"
            )
            ctes.append(f"{cte_alias} AS (\n  {inner}\n)")
            views[nid] = _NodeView(cte_alias=cte_alias, columns=out_cols)
            continue

        if ntype == "output":
            if len(preds) != 1:
                raise PipelineCompileError(f"output node {nid} requires exactly one input")
            up = views[preds[0]["source_node_id"]]
            # No CTE; the output node selects from its predecessor in the final SELECT.
            views[nid] = _NodeView(cte_alias=up.cte_alias, columns=list(up.columns))
            continue

        raise PipelineCompileError(f"unknown node_type: {ntype}")

    # Final SELECT from the predecessor of the output node.
    out_pred = _predecessors(output_node["id"], edges)
    if len(out_pred) != 1:
        raise PipelineCompileError("output node requires exactly one input")
    final_view = views[out_pred[0]["source_node_id"]]

    cte_block = "WITH " + ",\n".join(ctes) if ctes else ""
    final_select = f"SELECT * FROM {final_view.cte_alias}"
    sql = f"{cte_block}\n{final_select}".strip() if cte_block else final_select

    out_cfg = output_node.get("config") or {}
    return CompiledPipeline(
        sql=sql,
        output_columns=list(final_view.columns),
        dataset_ids=list(dict.fromkeys(referenced_dataset_ids)),
        output_node_id=output_node["id"],
        output_name=out_cfg.get("name") or "pipeline_output",
        output_description=out_cfg.get("description"),
    )
