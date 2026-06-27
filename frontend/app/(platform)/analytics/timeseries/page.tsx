"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { analyzeTimeSeries, apiFetch, type TimeSeriesAnalysis } from "@/lib/api";
import type { Dataset, DatasetDetail } from "@/lib/types";

export default function AnalyticsTimeseriesPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [timeColumn, setTimeColumn] = useState("");
  const [valueColumn, setValueColumn] = useState("");
  const [resampleFreq, setResampleFreq] = useState("");
  const [rollingWindow, setRollingWindow] = useState("7");
  const [operations, setOperations] = useState<string[]>(["rolling", "regression"]);
  const [result, setResult] = useState<TimeSeriesAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Dataset[]>("/catalog/datasets")
      .then((rows) => {
        setDatasets(rows);
        setDatasetId(rows[0]?.id ?? "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unable to load datasets."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!datasetId) return;
    apiFetch<DatasetDetail>(`/catalog/datasets/${datasetId}`)
      .then((row) => {
        setDetail(row);
        setTimeColumn(row.columns[0]?.name ?? "");
        setValueColumn(row.columns[1]?.name ?? row.columns[0]?.name ?? "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unable to load dataset schema."));
  }, [datasetId]);

  const rows = useMemo(() => {
    if (!result) return [];
    return result.time.map((time, index) => ({
      time,
      raw: result.raw[index],
      rolling: result.rolling?.values[index],
      regression: result.regression?.line[index],
    }));
  }, [result]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setResult(await analyzeTimeSeries({
        dataset_id: datasetId,
        time_column: timeColumn,
        value_column: valueColumn,
        operations,
        resample_freq: resampleFreq || null,
        rolling_window: Number(rollingWindow || 7),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Time-series analysis failed.");
    } finally {
      setBusy(false);
    }
  }

  function toggleOperation(name: string) {
    setOperations((prev) => prev.includes(name) ? prev.filter((item) => item !== name) : [...prev, name]);
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Time-series analysis" type="Analytics" status={result ? `${result.n} points` : "Ready"} />
      {loading ? <LoadingState label="Loading datasets..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading ? (
        <form className="app-card grid gap-3 p-4 md:grid-cols-6" onSubmit={submit}>
          <label className="block text-xs font-medium text-[var(--muted)] md:col-span-2">
            Dataset
            <select className="input-dark mt-1 w-full" value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
              {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}
            </select>
          </label>
          <label className="block text-xs font-medium text-[var(--muted)]">
            Time column
            <select className="input-dark mt-1 w-full" value={timeColumn} onChange={(event) => setTimeColumn(event.target.value)}>
              {detail?.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
            </select>
          </label>
          <label className="block text-xs font-medium text-[var(--muted)]">
            Value column
            <select className="input-dark mt-1 w-full" value={valueColumn} onChange={(event) => setValueColumn(event.target.value)}>
              {detail?.columns.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
            </select>
          </label>
          <label className="block text-xs font-medium text-[var(--muted)]">
            Resample
            <input className="input-dark mt-1 w-full" value={resampleFreq} onChange={(event) => setResampleFreq(event.target.value)} placeholder="D, W, M" />
          </label>
          <label className="block text-xs font-medium text-[var(--muted)]">
            Window
            <input className="input-dark mt-1 w-full" value={rollingWindow} onChange={(event) => setRollingWindow(event.target.value)} inputMode="numeric" />
          </label>
          <div className="flex flex-wrap items-end gap-2 md:col-span-5">
            {["rolling", "regression", "fft"].map((name) => (
              <button key={name} type="button" className={`toolbar-button ${operations.includes(name) ? "border-emerald-400/40" : ""}`} onClick={() => toggleOperation(name)}>
                {name}
              </button>
            ))}
          </div>
          <button className="toolbar-button justify-center" type="submit" disabled={busy || !datasetId || !timeColumn || !valueColumn}>
            {busy ? "Analyzing" : "Run"}
          </button>
        </form>
      ) : null}

      {result ? (
        <section className="app-card overflow-hidden">
          <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
            <h2 className="font-semibold">{result.dataset_name}</h2>
          </div>
          <table className="data-table text-sm">
            <thead><tr><th>Time</th><th>Raw</th><th>Rolling</th><th>Regression</th></tr></thead>
            <tbody>{rows.slice(0, 200).map((row) => (
              <tr key={row.time}>
                <td className="font-mono">{row.time}</td>
                <td>{row.raw}</td>
                <td>{row.rolling ?? "-"}</td>
                <td>{row.regression ?? "-"}</td>
              </tr>
            ))}</tbody>
          </table>
        </section>
      ) : !loading ? (
        <EmptyState title="No analysis yet" detail="Choose a dataset, time column, and value column to run analysis." />
      ) : null}
    </div>
  );
}
