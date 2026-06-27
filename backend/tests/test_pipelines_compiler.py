"""Unit tests for the pipeline graph → SQL compiler."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from app.pipelines.compiler import PipelineCompileError, compile_pipeline


@dataclass
class _DS:
    id: UUID
    schema_name: str
    table_name: str


@dataclass
class _Col:
    name: str


def _src(dataset_id: UUID, node_id: str = "n_src"):
    return {
        "id": node_id,
        "node_type": "source",
        "config": {"dataset_id": str(dataset_id)},
    }


def _output(node_id: str = "n_out", name: str = "out"):
    return {
        "id": node_id,
        "node_type": "output",
        "config": {"name": name, "materialize": "view"},
    }


def _edge(src: str, tgt: str, handle: str = "in"):
    return {"id": f"e_{src}_{tgt}", "source_node_id": src, "target_node_id": tgt, "target_handle": handle}


def test_single_source_to_output():
    ds = _DS(id=uuid4(), schema_name="public", table_name="customers")
    cols = {ds.id: [_Col("id"), _Col("name")]}
    compiled = compile_pipeline(
        nodes=[_src(ds.id, "s1"), _output("out")],
        edges=[_edge("s1", "out")],
        datasets=[ds],
        dataset_columns_by_id=cols,
    )
    assert "WITH" in compiled.sql
    assert '"public"."customers"' in compiled.sql
    assert compiled.output_columns == ["id", "name"]
    assert compiled.dataset_ids == [ds.id]


def test_join_with_keys_emits_join_sql():
    a = _DS(id=uuid4(), schema_name="public", table_name="customers")
    b = _DS(id=uuid4(), schema_name="public", table_name="orders")
    cols = {
        a.id: [_Col("id"), _Col("name")],
        b.id: [_Col("id"), _Col("customer_id"), _Col("amount")],
    }
    compiled = compile_pipeline(
        nodes=[
            _src(a.id, "sa"),
            _src(b.id, "sb"),
            {
                "id": "j",
                "node_type": "join",
                "config": {"join_type": "inner", "left_keys": ["id"], "right_keys": ["customer_id"]},
            },
            _output("out"),
        ],
        edges=[
            _edge("sa", "j", "left"),
            _edge("sb", "j", "right"),
            _edge("j", "out"),
        ],
        datasets=[a, b],
        dataset_columns_by_id=cols,
    )
    assert "INNER JOIN" in compiled.sql
    assert 'l."id" = r."customer_id"' in compiled.sql
    # right.id collides with left.id → suffixed
    assert "id_r" in compiled.output_columns


def test_filter_passthrough_without_where():
    ds = _DS(id=uuid4(), schema_name="public", table_name="t")
    cols = {ds.id: [_Col("a"), _Col("b")]}
    compiled = compile_pipeline(
        nodes=[
            _src(ds.id, "s"),
            {"id": "f", "node_type": "filter", "config": {"where": ""}},
            _output("out"),
        ],
        edges=[_edge("s", "f"), _edge("f", "out")],
        datasets=[ds],
        dataset_columns_by_id=cols,
    )
    # No WHERE because the user didn't supply one.
    assert "WHERE" not in compiled.sql.upper().replace("CWHERE", "")
    assert compiled.output_columns == ["a", "b"]


def test_filter_with_where_clause():
    ds = _DS(id=uuid4(), schema_name="public", table_name="t")
    cols = {ds.id: [_Col("a")]}
    compiled = compile_pipeline(
        nodes=[
            _src(ds.id, "s"),
            {"id": "f", "node_type": "filter", "config": {"where": "a > 10"}},
            _output("out"),
        ],
        edges=[_edge("s", "f"), _edge("f", "out")],
        datasets=[ds],
        dataset_columns_by_id=cols,
    )
    assert "WHERE a > 10" in compiled.sql


def test_formula_appends_columns():
    ds = _DS(id=uuid4(), schema_name="public", table_name="orders")
    cols = {ds.id: [_Col("amount")]}
    compiled = compile_pipeline(
        nodes=[
            _src(ds.id, "s"),
            {
                "id": "fm",
                "node_type": "formula",
                "config": {"columns": [{"name": "tax", "expr": "amount * 0.2"}]},
            },
            _output("out"),
        ],
        edges=[_edge("s", "fm"), _edge("fm", "out")],
        datasets=[ds],
        dataset_columns_by_id=cols,
    )
    assert "(amount * 0.2) AS \"tax\"" in compiled.sql
    assert "tax" in compiled.output_columns


def test_select_renames_and_filters_columns():
    ds = _DS(id=uuid4(), schema_name="public", table_name="t")
    cols = {ds.id: [_Col("id"), _Col("name"), _Col("created_at")]}
    compiled = compile_pipeline(
        nodes=[
            _src(ds.id, "s"),
            {
                "id": "sel",
                "node_type": "select",
                "config": {"columns": ["id", "created_at"], "rename": {"created_at": "ts"}},
            },
            _output("out"),
        ],
        edges=[_edge("s", "sel"), _edge("sel", "out")],
        datasets=[ds],
        dataset_columns_by_id=cols,
    )
    assert '"created_at" AS "ts"' in compiled.sql
    assert compiled.output_columns == ["id", "ts"]


def test_select_unknown_column_rejected():
    ds = _DS(id=uuid4(), schema_name="public", table_name="t")
    cols = {ds.id: [_Col("id")]}
    with pytest.raises(PipelineCompileError, match="unknown column"):
        compile_pipeline(
            nodes=[
                _src(ds.id, "s"),
                {"id": "sel", "node_type": "select", "config": {"columns": ["nope"]}},
                _output("out"),
            ],
            edges=[_edge("s", "sel"), _edge("sel", "out")],
            datasets=[ds],
            dataset_columns_by_id=cols,
        )


def test_missing_output_rejected():
    ds = _DS(id=uuid4(), schema_name="public", table_name="t")
    cols = {ds.id: [_Col("a")]}
    with pytest.raises(PipelineCompileError, match="output"):
        compile_pipeline(
            nodes=[_src(ds.id, "s")],
            edges=[],
            datasets=[ds],
            dataset_columns_by_id=cols,
        )


def test_cycle_rejected():
    ds = _DS(id=uuid4(), schema_name="public", table_name="t")
    cols = {ds.id: [_Col("a")]}
    # filter → filter → output, with a back-edge filter1 ← filter2 forming a cycle
    nodes = [
        _src(ds.id, "s"),
        {"id": "f1", "node_type": "filter", "config": {"where": ""}},
        {"id": "f2", "node_type": "filter", "config": {"where": ""}},
        _output("out"),
    ]
    edges = [
        _edge("s", "f1"),
        _edge("f1", "f2"),
        _edge("f2", "f1"),  # back-edge
        _edge("f2", "out"),
    ]
    with pytest.raises(PipelineCompileError, match="cycle"):
        compile_pipeline(nodes=nodes, edges=edges, datasets=[ds], dataset_columns_by_id=cols)


def test_join_missing_handle_rejected():
    a = _DS(id=uuid4(), schema_name="public", table_name="a")
    b = _DS(id=uuid4(), schema_name="public", table_name="b")
    cols = {a.id: [_Col("id")], b.id: [_Col("id")]}
    nodes = [
        _src(a.id, "sa"),
        _src(b.id, "sb"),
        {"id": "j", "node_type": "join", "config": {"left_keys": ["id"], "right_keys": ["id"]}},
        _output("out"),
    ]
    # Both inputs connect to "in" — should fail
    edges = [
        _edge("sa", "j", "in"),
        _edge("sb", "j", "in"),
        _edge("j", "out"),
    ]
    with pytest.raises(PipelineCompileError, match="left.*right"):
        compile_pipeline(nodes=nodes, edges=edges, datasets=[a, b], dataset_columns_by_id=cols)


def test_unknown_source_dataset_rejected():
    ds = _DS(id=uuid4(), schema_name="public", table_name="t")
    other = uuid4()
    cols = {ds.id: [_Col("a")]}
    with pytest.raises(PipelineCompileError, match="source dataset not found"):
        compile_pipeline(
            nodes=[
                {"id": "s", "node_type": "source", "config": {"dataset_id": str(other)}},
                _output("out"),
            ],
            edges=[_edge("s", "out")],
            datasets=[ds],
            dataset_columns_by_id=cols,
        )


def test_union_all_two_inputs():
    a = _DS(id=uuid4(), schema_name="public", table_name="a")
    b = _DS(id=uuid4(), schema_name="public", table_name="b")
    cols = {a.id: [_Col("x")], b.id: [_Col("x")]}
    compiled = compile_pipeline(
        nodes=[
            _src(a.id, "sa"),
            _src(b.id, "sb"),
            {"id": "u", "node_type": "union", "config": {"distinct": False}},
            _output("out"),
        ],
        edges=[_edge("sa", "u"), _edge("sb", "u"), _edge("u", "out")],
        datasets=[a, b],
        dataset_columns_by_id=cols,
    )
    assert "UNION ALL" in compiled.sql


def test_trained_model_appends_prediction_column():
    ds = _DS(id=uuid4(), schema_name="public", table_name="features")
    cols = {ds.id: [_Col("id"), _Col("amount")]}
    compiled = compile_pipeline(
        nodes=[
            _src(ds.id, "s"),
            {
                "id": "m",
                "node_type": "trained_model",
                "config": {"model_id": str(uuid4()), "version_id": str(uuid4()), "prediction_column": "score"},
            },
            _output("out"),
        ],
        edges=[_edge("s", "m"), _edge("m", "out")],
        datasets=[ds],
        dataset_columns_by_id=cols,
    )
    assert 'NULL::double precision AS "score"' in compiled.sql
    assert compiled.output_columns == ["id", "amount", "score"]
