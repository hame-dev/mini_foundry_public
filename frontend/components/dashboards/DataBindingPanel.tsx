"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Binding, DashboardComponent } from "@/lib/dashboards";
import type { Dataset } from "@/lib/types";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

type Props = {
  component: DashboardComponent;
  onChange: (next: DashboardComponent) => void;
};

type Tab = "sql_query" | "dataset" | "static";

export default function DataBindingPanel({ component, onChange }: Props) {
  const initialTab: Tab = component.data_binding?.type === "dataset" ? "dataset"
    : component.data_binding?.type === "static" ? "static" : "sql_query";
  const [tab, setTab] = useState<Tab>(initialTab);
  const [datasets, setDatasets] = useState<Dataset[]>([]);

  useEffect(() => {
    apiFetch<Dataset[]>("/catalog/datasets").then(setDatasets).catch(() => undefined);
  }, []);

  function setBinding(next: Binding) {
    onChange({ ...component, data_binding: next });
  }

  return (
    <div className="space-y-3 no-drag">
      <h3 className="text-xs uppercase tracking-wide text-gray-500">Data binding</h3>
      <div className="flex gap-1 text-xs border-b">
        {(["sql_query", "dataset", "static"] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-3 py-1 ${tab === t ? "border-b-2 border-black font-medium" : "text-gray-500"}`}>
            {t}
          </button>
        ))}
      </div>

      {tab === "sql_query" && (
        <SqlTab
          binding={component.data_binding?.type === "sql_query" ? component.data_binding : { type: "sql_query", sql: "SELECT 1", dataset_ids: [] }}
          datasets={datasets}
          onChange={setBinding}
        />
      )}
      {tab === "dataset" && (
        <DatasetTab
          binding={component.data_binding?.type === "dataset" ? component.data_binding : { type: "dataset", dataset_id: datasets[0]?.id ?? "" }}
          datasets={datasets}
          onChange={setBinding}
        />
      )}
      {tab === "static" && (
        <StaticTab
          binding={component.data_binding?.type === "static" ? component.data_binding : { type: "static", rows: [] }}
          onChange={setBinding}
        />
      )}
    </div>
  );
}

function SqlTab({ binding, datasets, onChange }: {
  binding: Extract<Binding, { type: "sql_query" }>;
  datasets: Dataset[];
  onChange: (b: Binding) => void;
}) {
  return (
    <>
      <div className="border rounded overflow-hidden h-40">
        <MonacoEditor
          language="sql"
          value={binding.sql}
          onChange={(v) => onChange({ ...binding, sql: v ?? "" })}
          options={{ minimap: { enabled: false }, fontSize: 12 }}
        />
      </div>
      <div>
        <label className="block text-xs mb-1">Referenced datasets (for permission check)</label>
        <div className="space-y-1 max-h-32 overflow-auto border rounded p-2">
          {datasets.map((d) => (
            <label key={d.id} className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={binding.dataset_ids.includes(d.id)}
                onChange={(e) => {
                  const next = e.target.checked
                    ? [...binding.dataset_ids, d.id]
                    : binding.dataset_ids.filter((x) => x !== d.id);
                  onChange({ ...binding, dataset_ids: next });
                }}
              />
              <span className="truncate">{d.name}</span>
            </label>
          ))}
        </div>
      </div>
    </>
  );
}

function DatasetTab({ binding, datasets, onChange }: {
  binding: Extract<Binding, { type: "dataset" }>;
  datasets: Dataset[];
  onChange: (b: Binding) => void;
}) {
  const metrics = binding.metrics || [];
  return (
    <>
      <div>
        <label className="block text-xs mb-1">Dataset</label>
        <select className="w-full border rounded px-2 py-1 text-sm"
          value={binding.dataset_id}
          onChange={(e) => onChange({ ...binding, dataset_id: e.target.value })}>
          <option value="">— select —</option>
          {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </div>
      <div>
        <label className="block text-xs mb-1">group_by (comma-separated columns)</label>
        <input className="w-full border rounded px-2 py-1 text-sm"
          value={(binding.group_by || []).join(",")}
          onChange={(e) => onChange({ ...binding, group_by: e.target.value ? e.target.value.split(",").map((s) => s.trim()) : [] })} />
      </div>
      <div>
        <label className="block text-xs mb-1">metrics</label>
        <div className="space-y-1">
          {metrics.map((m, i) => (
            <div key={i} className="flex gap-1 text-xs">
              <select className="border rounded px-1"
                value={m.aggregation}
                onChange={(e) => {
                  const next = [...metrics];
                  next[i] = { ...m, aggregation: e.target.value as never };
                  onChange({ ...binding, metrics: next });
                }}>
                {["count", "sum", "avg", "min", "max"].map((a) => <option key={a}>{a}</option>)}
              </select>
              <input className="border rounded px-1 flex-1" placeholder="column (* for all)"
                value={m.column}
                onChange={(e) => {
                  const next = [...metrics];
                  next[i] = { ...m, column: e.target.value };
                  onChange({ ...binding, metrics: next });
                }} />
              <input className="border rounded px-1 w-24" placeholder="alias"
                value={m.alias}
                onChange={(e) => {
                  const next = [...metrics];
                  next[i] = { ...m, alias: e.target.value };
                  onChange({ ...binding, metrics: next });
                }} />
              <button className="text-red-600 px-1"
                onClick={() => onChange({ ...binding, metrics: metrics.filter((_, j) => j !== i) })}>×</button>
            </div>
          ))}
        </div>
        <button
          className="mt-1 text-xs border rounded px-2 py-1"
          onClick={() => onChange({ ...binding, metrics: [...metrics, { column: "*", aggregation: "count", alias: "count" }] })}>
          + add metric
        </button>
      </div>
    </>
  );
}

function StaticTab({ binding, onChange }: {
  binding: Extract<Binding, { type: "static" }>;
  onChange: (b: Binding) => void;
}) {
  const [text, setText] = useState(JSON.stringify(binding.rows, null, 2));
  const [err, setErr] = useState<string | null>(null);

  return (
    <div>
      <label className="block text-xs mb-1">Static rows (JSON array of objects)</label>
      <textarea className="w-full border rounded p-2 text-xs font-mono h-40"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const parsed = JSON.parse(e.target.value);
            if (!Array.isArray(parsed)) throw new Error("must be an array");
            onChange({ type: "static", rows: parsed });
            setErr(null);
          } catch (x: unknown) {
            setErr(x instanceof Error ? x.message : String(x));
          }
        }} />
      {err && <div className="text-xs text-red-600 mt-1">{err}</div>}
    </div>
  );
}
