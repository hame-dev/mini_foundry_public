"use client";

import { useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";

import { apiFetch, analyzeTimeSeries, ApiError, type TimeSeriesAnalysis } from "@/lib/api";
import { ResourceHeader } from "@/components/foundry/FoundryPrimitives";

type DatasetSummary = { id: string; name: string };
type Column = { name: string; data_type: string | null };
type DatasetDetail = DatasetSummary & { columns: Column[] };

const OPERATIONS = ["rolling", "regression", "fft"] as const;
const RESAMPLE_OPTIONS = [
  { value: "", label: "None (raw timestamps)" },
  { value: "H", label: "Hourly" },
  { value: "D", label: "Daily" },
  { value: "W", label: "Weekly" },
  { value: "M", label: "Monthly" },
];

const TIME_HINTS = ["date", "time", "timestamp", "datetime", "created", "updated", "ts"];

function looksLikeTime(col: Column): boolean {
  const t = (col.data_type || "").toLowerCase();
  const n = col.name.toLowerCase();
  return t.includes("date") || t.includes("time") || TIME_HINTS.some((h) => n.includes(h));
}

function looksNumeric(col: Column): boolean {
  const t = (col.data_type || "").toLowerCase();
  return ["int", "float", "double", "numeric", "decimal", "real", "bigint"].some((k) => t.includes(k));
}

export default function QuiverPage() {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [timeColumn, setTimeColumn] = useState("");
  const [valueColumn, setValueColumn] = useState("");
  const [resampleFreq, setResampleFreq] = useState("");
  const [rollingWindow, setRollingWindow] = useState(7);
  const [ops, setOps] = useState<Set<string>>(new Set(OPERATIONS));

  const [result, setResult] = useState<TimeSeriesAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<DatasetSummary[]>("/datasets")
      .then(setDatasets)
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);

  useEffect(() => {
    if (!datasetId) {
      setDetail(null);
      return;
    }
    apiFetch<DatasetDetail>(`/datasets/${datasetId}`)
      .then((d) => {
        setDetail(d);
        const t = d.columns.find(looksLikeTime);
        const v = d.columns.find((c) => looksNumeric(c) && c.name !== t?.name);
        setTimeColumn(t?.name ?? d.columns[0]?.name ?? "");
        setValueColumn(v?.name ?? d.columns.find((c) => c.name !== t?.name)?.name ?? "");
        setResult(null);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, [datasetId]);

  function toggleOp(op: string) {
    setOps((prev) => {
      const next = new Set(prev);
      next.has(op) ? next.delete(op) : next.add(op);
      return next;
    });
  }

  async function run() {
    if (!datasetId || !timeColumn || !valueColumn) return;
    setLoading(true);
    setError(null);
    try {
      const analysis = await analyzeTimeSeries({
        dataset_id: datasetId,
        time_column: timeColumn,
        value_column: valueColumn,
        operations: ["raw", ...ops],
        resample_freq: resampleFreq || null,
        rolling_window: rollingWindow,
      });
      setResult(analysis);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  const seriesOption = useMemo(() => {
    if (!result || !result.n) return null;
    const series: Record<string, unknown>[] = [
      { type: "line", name: valueColumn, data: result.raw, smooth: false, showSymbol: false },
    ];
    if (result.rolling) {
      series.push({
        type: "line",
        name: `rolling avg (${result.rolling.window})`,
        data: result.rolling.values,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2 },
      });
    }
    if (result.regression) {
      series.push({
        type: "line",
        name: "trend",
        data: result.regression.line,
        smooth: false,
        showSymbol: false,
        lineStyle: { type: "dashed" },
      });
    }
    return {
      tooltip: { trigger: "axis" },
      legend: { top: 0 },
      grid: { left: 48, right: 16, top: 28, bottom: 40 },
      xAxis: { type: "category", data: result.time, axisLabel: { hideOverlap: true } },
      yAxis: { type: "value", scale: true },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 6 }],
      series,
    };
  }, [result, valueColumn]);

  const fftOption = useMemo(() => {
    if (!result?.fft || !result.fft.freq.length) return null;
    return {
      tooltip: {
        trigger: "axis",
        formatter: (params: { dataIndex: number }[]) => {
          const i = params[0]?.dataIndex ?? 0;
          const f = result.fft!.freq[i];
          const p = result.fft!.period[i];
          const a = result.fft!.amplitude[i];
          return `freq ${f.toFixed(4)} cyc/sample<br/>period ${p.toFixed(1)} samples<br/>amp ${a.toFixed(3)}`;
        },
      },
      grid: { left: 48, right: 16, top: 16, bottom: 40 },
      xAxis: {
        type: "category",
        name: "cycles/sample",
        nameLocation: "middle",
        nameGap: 26,
        data: result.fft.freq.map((f) => f.toFixed(4)),
      },
      yAxis: { type: "value", name: "amplitude" },
      series: [{ type: "bar", data: result.fft.amplitude }],
    };
  }, [result]);

  return (
    <div className="flex flex-col gap-4">
      <ResourceHeader
        eyebrow="Analyze"
        title="Quiver"
        subtitle="Time-series analysis — rolling averages, trend regression, and frequency (FFT) spectra."
      />

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-3 app-card p-3 space-y-3">
          <div>
            <div className="panel-heading mb-1">Dataset</div>
            <select
              className="input-dark w-full"
              value={datasetId}
              onChange={(e) => setDatasetId(e.target.value)}
            >
              <option value="">Select a dataset…</option>
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
          </div>

          <div>
            <div className="panel-heading mb-1">Time column</div>
            <select
              className="input-dark w-full"
              value={timeColumn}
              onChange={(e) => setTimeColumn(e.target.value)}
              disabled={!detail}
            >
              {detail?.columns.map((c) => (
                <option key={c.name} value={c.name}>{c.name}{c.data_type ? ` (${c.data_type})` : ""}</option>
              ))}
            </select>
          </div>

          <div>
            <div className="panel-heading mb-1">Value column</div>
            <select
              className="input-dark w-full"
              value={valueColumn}
              onChange={(e) => setValueColumn(e.target.value)}
              disabled={!detail}
            >
              {detail?.columns.map((c) => (
                <option key={c.name} value={c.name}>{c.name}{c.data_type ? ` (${c.data_type})` : ""}</option>
              ))}
            </select>
          </div>

          <div>
            <div className="panel-heading mb-1">Resample</div>
            <select
              className="input-dark w-full"
              value={resampleFreq}
              onChange={(e) => setResampleFreq(e.target.value)}
            >
              {RESAMPLE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          <div>
            <div className="panel-heading mb-1">Rolling window</div>
            <input
              type="number"
              min={1}
              className="input-dark w-full"
              value={rollingWindow}
              onChange={(e) => setRollingWindow(Math.max(1, Number(e.target.value) || 1))}
            />
          </div>

          <div>
            <div className="panel-heading mb-1">Overlays</div>
            <div className="space-y-1 text-sm">
              {OPERATIONS.map((op) => (
                <label key={op} className="flex items-center gap-2 capitalize">
                  <input type="checkbox" checked={ops.has(op)} onChange={() => toggleOp(op)} />
                  {op === "fft" ? "FFT spectrum" : op}
                </label>
              ))}
            </div>
          </div>

          <button
            className="btn-primary w-full justify-center disabled:opacity-50"
            onClick={run}
            disabled={loading || !datasetId || !timeColumn || !valueColumn}
          >
            {loading ? "Analyzing…" : "Analyze"}
          </button>

          {error ? <div className="badge badge-danger text-xs">{error}</div> : null}
        </div>

        <div className="col-span-9 flex flex-col gap-4">
          {result && result.n ? (
            <>
              <div className="app-card p-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="font-semibold text-sm">{result.dataset_name}</div>
                  <div className="text-xs flex gap-3">
                    <span>{result.n.toLocaleString()} points</span>
                    {result.regression ? (
                      <>
                        <span>slope {result.regression.slope.toFixed(4)}/sample</span>
                        <span>R² {result.regression.r2.toFixed(3)}</span>
                      </>
                    ) : null}
                  </div>
                </div>
                {seriesOption ? (
                  <ReactECharts option={seriesOption} style={{ height: 360, width: "100%" }} />
                ) : null}
              </div>

              {fftOption ? (
                <div className="app-card p-3">
                  <div className="font-semibold text-sm mb-2">Frequency spectrum (FFT)</div>
                  <ReactECharts option={fftOption} style={{ height: 240, width: "100%" }} />
                </div>
              ) : null}
            </>
          ) : (
            <div className="app-card empty-state p-8">
              <div className="empty-state-title">No analysis yet</div>
              <p className="text-sm">
                Pick a dataset, a time column, and a numeric value column, then run the analysis.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
