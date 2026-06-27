"use client";

import Link from "next/link";
import { use, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { DatasetDetail } from "@/lib/types";

type ExploreStep = {
  type: "filter" | "aggregate";
  column?: string;
  op?: string;
  value?: unknown;
  group_by?: string[];
  metrics?: { column: string; aggregation: string; alias: string }[];
};

function formatStepValue(value: unknown): string {
  if (typeof value === "string") return `"${value}"`;
  if (value === null || value === undefined) return "null";
  return String(value);
}

export default function DatasetExplorePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [steps, setSteps] = useState<ExploreStep[]>([]);
  const [result, setResult] = useState<{ columns: string[]; rows: Record<string, unknown>[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [showAddModal, setShowAddModal] = useState(false);
  const [newStepType, setNewStepType] = useState<"filter" | "aggregate">("filter");
  const [filterCol, setFilterCol] = useState("");
  const [filterOp, setFilterOp] = useState("==");
  const [filterVal, setFilterVal] = useState("");
  const [aggGroupBy, setAggGroupBy] = useState<string[]>([]);
  const [aggMetrics, setAggMetrics] = useState<{ column: string; aggregation: string; alias: string }[]>([]);
  const [newMetricCol, setNewMetricCol] = useState("");
  const [newMetricAgg, setNewMetricAgg] = useState("count");

  useEffect(() => {
    setDetailError(null);
    apiFetch<DatasetDetail>(`/catalog/datasets/${id}`)
      .then((data) => {
        setDetail(data);
        if (data.columns.length > 0) {
          setFilterCol(data.columns[0].name);
          setNewMetricCol(data.columns[0].name);
        }
      })
      .catch((e) => setDetailError(e instanceof Error ? e.message : "Unable to load dataset."));
  }, [id]);

  useEffect(() => {
    if (!detail) return;
    const timer = window.setTimeout(() => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      setError(null);
      apiFetch<{ columns: string[]; rows: Record<string, unknown>[] }>(
        `/catalog/datasets/${id}/explore`,
        {
          method: "POST",
          body: JSON.stringify({ steps }),
          signal: controller.signal,
        },
      )
        .then((data) => {
          if (!controller.signal.aborted) setResult(data);
        })
        .catch((e) => {
          if (controller.signal.aborted) return;
          setError(e instanceof Error ? e.message : "Query failed");
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 300);
    return () => {
      window.clearTimeout(timer);
      abortRef.current?.abort();
    };
  }, [steps, id, detail]);

  useEffect(() => {
    if (!showAddModal) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setShowAddModal(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showAddModal]);

  if (!detail && detailError) {
    return <div className="p-6 text-sm font-semibold text-red-600">Unable to load analysis board: {detailError}</div>;
  }
  if (!detail) return <div className="p-6 text-gray-500 font-medium">Loading analysis board...</div>;

  const datasetDetail = detail;
  const cols = datasetDetail.columns.map((c) => c.name);

  function handleAddStep(e: React.FormEvent) {
    e.preventDefault();
    let step: ExploreStep;
    if (newStepType === "filter") {
      const selectedColumn = datasetDetail.columns.find((c) => c.name === filterCol);
      const dataType = (selectedColumn?.data_type ?? "").toLowerCase();
      const numeric = /(int|float|double|decimal|numeric|real|bigint|smallint)/.test(dataType);
      const bool = /bool/.test(dataType);
      let parsedValue: unknown = filterVal;
      if (numeric && filterVal.trim() !== "" && Number.isFinite(Number(filterVal))) {
        parsedValue = Number(filterVal);
      } else if (bool && /^(true|false)$/i.test(filterVal.trim())) {
        parsedValue = filterVal.trim().toLowerCase() === "true";
      }
      step = { type: "filter", column: filterCol, op: filterOp, value: parsedValue };
    } else {
      step = {
        type: "aggregate",
        group_by: aggGroupBy,
        metrics: aggMetrics.length ? aggMetrics : [{ column: "*", aggregation: "count", alias: "count_all" }],
      };
    }
    setSteps([...steps, step]);
    setShowAddModal(false);
    setFilterVal("");
    setAggGroupBy([]);
    setAggMetrics([]);
  }

  function removeStep(idx: number) {
    setSteps(steps.filter((_, i) => i !== idx));
  }

  function moveStep(idx: number, direction: -1 | 1) {
    const next = [...steps];
    const target = idx + direction;
    if (target < 0 || target >= next.length) return;
    [next[idx], next[target]] = [next[target], next[idx]];
    setSteps(next);
  }

  function addMetric() {
    if (!newMetricCol) return;
    const nextAlias = `${newMetricAgg.toLowerCase()}_${newMetricCol === "*" ? "all" : newMetricCol}`;
    setAggMetrics([...aggMetrics, { column: newMetricCol, aggregation: newMetricAgg, alias: nextAlias }]);
  }

  function toggleGroupBy(colName: string) {
    setAggGroupBy(aggGroupBy.includes(colName) ? aggGroupBy.filter((c) => c !== colName) : [...aggGroupBy, colName]);
  }

  return (
    <div className="flex h-[calc(100vh-140px)] gap-6 p-2 overflow-hidden">
      <div className="w-80 flex flex-col app-card overflow-hidden h-full">
        <div className="section-header flex items-center justify-between">
          <div>
            <Link href={`/data/datasets/${id}`} className="text-xs text-[var(--muted)] hover:underline">← Dataset</Link>
            <h2 className="section-header-title">Analysis Path (Contour)</h2>
          </div>
          <button onClick={() => setShowAddModal(true)} className="btn-primary px-2 py-1 text-xs font-semibold">+ Add Step</button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <div className="p-3 border border-blue-100 bg-blue-50/50 rounded-lg relative">
            <span className="text-[10px] uppercase tracking-wider font-bold text-blue-500">Step 1: Input</span>
            <h4 className="text-sm font-bold text-gray-900 mt-1">{detail.name}</h4>
            <p className="text-xs text-gray-500 mt-0.5">Base table: {detail.schema_name}.{detail.table_name}</p>
          </div>

          {steps.map((step, idx) => (
            <div key={idx} className="app-card p-3 relative group">
              <div className="absolute top-2 right-2 flex gap-1">
                <button type="button" onClick={() => moveStep(idx, -1)} disabled={idx === 0} className="btn-ghost px-1 py-0 text-xs">↑</button>
                <button type="button" onClick={() => moveStep(idx, 1)} disabled={idx === steps.length - 1} className="btn-ghost px-1 py-0 text-xs">↓</button>
                <button type="button" onClick={() => removeStep(idx)} className="text-gray-400 hover:text-red-600 font-bold text-sm">&times;</button>
              </div>
              <span className="text-[10px] uppercase tracking-wider font-bold text-gray-400">Step {idx + 2}: {step.type}</span>
              {step.type === "filter" ? (
                <div className="mt-1">
                  <span className="badge text-xs font-mono font-bold">{step.column}</span>
                  <span className="text-xs font-bold text-blue-600 mx-1">{step.op}</span>
                  <span className="text-xs font-semibold text-gray-900">{formatStepValue(step.value)}</span>
                </div>
              ) : (
                <div className="mt-1 space-y-1">
                  {step.group_by && step.group_by.length > 0 ? (
                    <div className="text-xs">
                      <span className="text-gray-500">Group by:</span>{" "}
                      {step.group_by.map((g) => <span key={g} className="badge font-mono mr-1">{g}</span>)}
                    </div>
                  ) : null}
                  {step.metrics?.map((m, mIdx) => (
                    <div key={mIdx} className="font-mono text-xs mt-0.5">
                      {m.aggregation.toUpperCase()}({m.column}) <span className="text-gray-400">as</span> {m.alias}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 flex flex-col app-card overflow-hidden h-full">
        <div className="section-header flex items-center justify-between">
          <div>
            <h3 className="section-header-title">Resulting Data</h3>
            <p className="text-xs text-gray-500 mt-0.5">After executing {steps.length + 1} analysis steps</p>
          </div>
          {loading ? <span className="text-xs text-blue-600 font-semibold animate-pulse">Running query...</span> : null}
        </div>

        <div className="flex-1 overflow-auto p-4">
          {error ? (
            <div className="p-4 bg-red-50 border border-red-100 rounded-lg text-sm text-red-600 font-semibold">Error resolving pipeline path: {error}</div>
          ) : loading && !result ? (
            <div className="h-full flex items-center justify-center text-gray-400 text-sm">Running analysis path…</div>
          ) : result && result.rows.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-gray-100 sticky top-0 text-left border-b border-gray-200">
                  <tr>{result.columns.map((c) => <th key={c} className="px-3 py-2 font-bold text-gray-700">{c}</th>)}</tr>
                </thead>
                <tbody>
                  {result.rows.map((row, rIdx) => (
                    <tr key={rIdx} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                      {result.columns.map((c) => <td key={c} className="px-3 py-1.5 font-mono text-gray-800">{String(row[c] ?? "")}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="h-full flex items-center justify-center text-gray-400 text-sm">
              {steps.length === 0 ? "Add analysis steps to explore this dataset." : "Query completed with zero rows."}
            </div>
          )}
        </div>
      </div>

      {showAddModal ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
          onClick={() => setShowAddModal(false)}
          role="presentation"
        >
          <div
            className="app-card rounded-xl shadow-2xl max-w-lg w-full overflow-hidden"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Add analysis step"
          >
            <div className="section-header flex items-center justify-between">
              <h3 className="section-header-title">Add Analysis Step</h3>
              <button type="button" onClick={() => setShowAddModal(false)} className="text-gray-400 hover:text-gray-600 text-xl font-medium">&times;</button>
            </div>
            <form onSubmit={handleAddStep}>
              <div className="p-6 space-y-4 max-h-[60vh] overflow-y-auto">
                <div className="flex gap-4 border-b border-gray-100 pb-3">
                  <label className="flex items-center gap-2 text-sm font-semibold cursor-pointer">
                    <input type="radio" checked={newStepType === "filter"} onChange={() => setNewStepType("filter")} />
                    Filter
                  </label>
                  <label className="flex items-center gap-2 text-sm font-semibold cursor-pointer">
                    <input type="radio" checked={newStepType === "aggregate"} onChange={() => setNewStepType("aggregate")} />
                    Aggregate / Group By
                  </label>
                </div>
                {newStepType === "filter" ? (
                  <div className="space-y-3">
                    <div className="flex flex-col gap-1">
                      <label className="text-xs font-bold text-gray-600">Column</label>
                      <select value={filterCol} onChange={(e) => setFilterCol(e.target.value)} className="input-dark px-3 py-1.5 text-sm">
                        {cols.map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-xs font-bold text-gray-600">Operator</label>
                      <select value={filterOp} onChange={(e) => setFilterOp(e.target.value)} className="input-dark px-3 py-1.5 text-sm">
                        <option value="==">equals (==)</option>
                        <option value="!=">not equals (!=)</option>
                        <option value=">">greater than</option>
                        <option value="<">less than</option>
                        <option value=">=">greater/equal</option>
                        <option value="<=">less/equal</option>
                        <option value="LIKE">matches SQL pattern (LIKE)</option>
                        <option value="ILIKE">matches SQL pattern case-insensitive (ILIKE)</option>
                      </select>
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-xs font-bold text-gray-600">Value</label>
                      <input type="text" value={filterVal} onChange={(e) => setFilterVal(e.target.value)} className="input-dark px-3 py-1.5 text-sm" required />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div>
                      <label className="text-xs font-bold text-gray-600 block mb-2">Group By Columns</label>
                      <div className="flex flex-wrap gap-2">
                        {cols.map((col) => (
                          <button key={col} type="button" onClick={() => toggleGroupBy(col)} className={`px-2.5 py-1 rounded-full text-xs font-semibold border ${aggGroupBy.includes(col) ? "btn-primary" : "btn-ghost"}`}>
                            {col}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="border-t border-gray-100 pt-3">
                      <label className="text-xs font-bold text-gray-600 block mb-2">Metrics / Aggregations</label>
                      <div className="flex gap-2 items-end mb-3">
                        <select value={newMetricCol} onChange={(e) => setNewMetricCol(e.target.value)} className="input-dark px-2 py-1.5 text-xs flex-1">
                          <option value="*">All Rows (*)</option>
                          {cols.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                        <select value={newMetricAgg} onChange={(e) => setNewMetricAgg(e.target.value)} className="input-dark px-2 py-1.5 text-xs flex-1">
                          <option value="count">COUNT</option>
                          <option value="sum">SUM</option>
                          <option value="avg">AVG</option>
                          <option value="min">MIN</option>
                          <option value="max">MAX</option>
                        </select>
                        <button type="button" onClick={addMetric} className="btn-ghost px-3 py-1.5 text-xs font-bold">Add Metric</button>
                      </div>
                      {aggMetrics.length > 0 ? (
                        <div className="space-y-1.5 max-h-32 overflow-y-auto border border-gray-200 rounded-lg p-2.5 bg-gray-50/50">
                          {aggMetrics.map((m, mIdx) => (
                            <div key={mIdx} className="flex justify-between items-center text-xs font-mono p-1.5 border rounded" style={{ background: "var(--panel-2)", borderColor: "var(--line)" }}>
                              <span>{m.aggregation.toUpperCase()}({m.column}) as <strong>{m.alias}</strong></span>
                              <button type="button" onClick={() => setAggMetrics(aggMetrics.filter((_, i) => i !== mIdx))} className="text-red-500 hover:text-red-700 font-bold">Delete</button>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>
                )}
              </div>
              <div className="px-6 py-4 flex items-center justify-end gap-3" style={{ borderTop: "1px solid var(--line)", background: "var(--panel-2)" }}>
                <button type="button" onClick={() => setShowAddModal(false)} className="btn-ghost px-4 py-2 text-sm font-medium">Cancel</button>
                <button type="submit" className="btn-primary px-4 py-2 text-sm font-semibold">Add Step</button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}
