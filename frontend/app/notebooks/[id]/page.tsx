"use client";
import dynamic from "next/dynamic";
import { use, useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import CellOutput from "@/components/notebooks/CellOutput";
import { BottomDrawer, ResourceHeader, ResourceToolbar, RightInspector } from "@/components/foundry/FoundryPrimitives";
import type { CellType, NotebookCell, NotebookDetail } from "@/lib/notebooks";
import { CELL_LABELS } from "@/lib/notebooks";
import type { Dataset } from "@/lib/types";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

export default function NotebookPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: notebookId } = use(params);
  const [nb, setNb] = useState<NotebookDetail | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const d = await apiFetch<NotebookDetail>(`/notebooks/${notebookId}`);
      setNb(d);
      await apiFetch("/activity/track", {
        method: "POST",
        body: JSON.stringify({ resource_type: "notebook", resource_id: notebookId, title: d.title, path: `/notebooks/${notebookId}` }),
      }).catch(() => {});
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [notebookId]);

  useEffect(() => {
    reload();
    apiFetch<Dataset[]>("/catalog/datasets").then(setDatasets).catch(() => undefined);
  }, [reload]);

  // Poll job status for any cell with last_status in {queued, running}.
  useEffect(() => {
    if (!nb) return;
    const pending = nb.cells.filter((c) => c.last_status === "queued" || c.last_status === "running");
    if (pending.length === 0) return;
    const id = setInterval(reload, 1000);
    return () => clearInterval(id);
  }, [nb, reload]);

  async function addCell(type: CellType) {
    await apiFetch(`/notebooks/${notebookId}/cells`, {
      method: "POST",
      body: JSON.stringify({ cell_type: type, source: defaultSource(type), dataset_ids: [] }),
    });
    reload();
  }

  if (error && !nb) return <div className="text-red-600">{error}</div>;
  if (!nb) return <div>Loading...</div>;

  async function removeNotebook() {
    if (!confirm("Delete this notebook?")) return;
    await apiFetch(`/notebooks/${notebookId}`, { method: "DELETE" });
    location.href = "/notebooks";
  }

  const allowedCells: CellType[] = nb.notebook_kind === "sql"
    ? ["markdown", "sql"]
    : ["markdown", "python", "ai_prompt"];

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <ResourceHeader
        eyebrow="Code Workspaces"
        title={nb.title}
        subtitle={nb.description ?? "Jupyter-style notebook workspace backed by the Mini Foundry sandbox."}
        tabs={[{ label: "Data", id: "Data" }, { label: "Packages", id: "Packages" }, { label: "Dashboards", id: "Dashboards" }, { label: "Models", id: "Models" }]}
        activeTab="Data"
        actions={<button onClick={removeNotebook} className="btn-ghost" style={{ color: "var(--danger)" }}>Delete</button>}
      />
      <ResourceToolbar>
        {["File", "Edit", "View", "Run", "Kernel", "Tabs", "Settings", "Help"].map((item) => <button key={item} className="btn-ghost">{item}</button>)}
        <span className="badge badge-success">{nb.kernel_name ?? (nb.notebook_kind === "sql" ? "SQL" : "Python 3")}</span>
        {allowedCells.map((t) => (
          <button key={t} onClick={() => addCell(t)} className="btn-primary">+ {CELL_LABELS[t]}</button>
        ))}
      </ResourceToolbar>

      {error && <div className="text-red-600 text-sm">{error}</div>}

      <div className="foundry-workbench" style={{ gridTemplateColumns: "260px minmax(0, 1fr) 300px" }}>
        <aside className="app-card" style={{ padding: 0 }}>
          <div className="panel-heading">Data</div>
          <div style={{ padding: 10, display: "grid", gap: 8, maxHeight: "calc(100vh - 360px)", overflow: "auto" }}>
            {datasets.map((d) => <span key={d.id} className="badge">{d.name}</span>)}
            {!datasets.length ? <span style={{ color: "var(--muted)" }}>No datasets visible</span> : null}
          </div>
          <div className="panel-heading">Packages</div>
          <div style={{ padding: 10, display: "flex", gap: 6, flexWrap: "wrap" }}>
            {(nb.requirements ?? []).map((r) => <span key={r} className="badge">{r}</span>)}
            {!(nb.requirements ?? []).length ? <span style={{ color: "var(--muted)" }}>No package metadata</span> : null}
          </div>
        </aside>
        <main style={{ display: "grid", gap: 10, alignContent: "start", minWidth: 0 }}>
          {nb.cells.map((cell) => (
            <CellCard key={cell.id} cell={cell} datasets={datasets} onChange={reload} />
          ))}
          {nb.cells.length === 0 && (
            <div className="app-card"><div className="empty-state"><div className="empty-state-title">Add a cell to start</div></div></div>
          )}
        </main>
        <RightInspector title="Workspace">
          <div><span className="stat-label">Kind</span><div className="stat-value">{nb.notebook_kind}</div></div>
          <div><span className="stat-label">AI policy</span><div className="stat-value">{nb.ai_policy}</div></div>
          <div><span className="stat-label">Cells</span><div className="stat-value">{nb.cells.length}</div></div>
        </RightInspector>
      </div>
      <BottomDrawer title="Kernel status" tabs={["Problems", "Preview", "Variables", "Terminal"]} active="Preview">
        <div style={{ color: "var(--muted)" }}>Kernel idle. Cell outputs render inline above; package and data context appears in the side panels.</div>
      </BottomDrawer>
    </div>
  );
}

function defaultSource(type: CellType): string {
  switch (type) {
    case "markdown": return "## New section\n\nNotes go here.";
    case "sql": return "SELECT 1 AS hello;";
    case "python": return "df = load_table('orders')\nprint(df.head())";
    case "ai_prompt": return "Load the orders dataset and plot a bar chart of order counts by status.";
  }
}

function CellCard({ cell, datasets, onChange }: { cell: NotebookCell; datasets: Dataset[]; onChange: () => void }) {
  const [source, setSource] = useState(cell.source);
  const [datasetIds, setDatasetIds] = useState<string[]>(cell.dataset_ids);
  const [runAfterGen, setRunAfterGen] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // keep local state in sync if the cell was polled and updated
  const lastSyncedSrc = useRef(cell.source);
  useEffect(() => {
    if (cell.source !== lastSyncedSrc.current) {
      setSource(cell.source);
      lastSyncedSrc.current = cell.source;
    }
  }, [cell.source]);

  async function save() {
    await apiFetch(`/notebooks/${cell.notebook_id}/cells/${cell.id}`, {
      method: "PUT",
      body: JSON.stringify({ source, dataset_ids: datasetIds }),
    });
  }

  async function run() {
    setBusy(true); setError(null);
    try {
      await save();
      await apiFetch(`/notebooks/${cell.notebook_id}/cells/${cell.id}/run`, {
        method: "POST",
        body: JSON.stringify({ run_after_generate: runAfterGen }),
      });
      onChange();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  async function remove() {
    if (!confirm("Delete cell?")) return;
    await apiFetch(`/notebooks/${cell.notebook_id}/cells/${cell.id}`, { method: "DELETE" });
    onChange();
  }

  const monacoLang =
    cell.cell_type === "sql" ? "sql" :
    cell.cell_type === "python" ? "python" :
    cell.cell_type === "markdown" ? "markdown" : "plaintext";

  return (
    <div className="app-card">
      <div className="section-header">
        <span className="section-header-title">{CELL_LABELS[cell.cell_type]}</span>
        <div className="flex items-center gap-2">
          {cell.last_status && <span className="text-gray-500">{cell.last_status}</span>}
          <button onClick={run} disabled={busy}
            className="btn-primary px-2 py-0.5 disabled:opacity-50">
            {busy ? "..." : "Run"}
          </button>
          <button onClick={remove} className="text-red-600">×</button>
        </div>
      </div>

      {(cell.cell_type === "sql" || cell.cell_type === "python") && (
        <DatasetPicker datasets={datasets} value={datasetIds} onChange={setDatasetIds} />
      )}

      {cell.cell_type === "ai_prompt" && (
        <div className="px-3 py-2 flex items-center gap-2 text-xs">
          <DatasetPicker datasets={datasets} value={datasetIds} onChange={setDatasetIds} compact />
          <label className="flex items-center gap-1 ml-auto">
            <input type="checkbox" checked={runAfterGen} onChange={(e) => setRunAfterGen(e.target.checked)} />
            Run after generate
          </label>
        </div>
      )}

      <div className="h-40">
        <MonacoEditor
          language={monacoLang}
          value={source}
          onChange={(v) => setSource(v ?? "")}
          options={{ minimap: { enabled: false }, fontSize: 13 }}
        />
      </div>

      {error && <div className="text-xs text-red-600 px-3 py-1">{error}</div>}

      <div className="border-t p-3">
        <CellOutput cell={cell} />
      </div>
    </div>
  );
}

function DatasetPicker({ datasets, value, onChange, compact = false }: {
  datasets: Dataset[]; value: string[]; onChange: (ids: string[]) => void; compact?: boolean;
}) {
  function toggle(id: string) {
    onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id]);
  }
  return (
    <div className={compact ? "" : "px-3 py-2 border-b text-xs"}>
      {!compact && <div className="mb-1 text-gray-500">Datasets:</div>}
      <div className="flex flex-wrap gap-1">
        {datasets.map((d) => (
          <button key={d.id} type="button" onClick={() => toggle(d.id)}
            style={value.includes(d.id)
              ? { background: "var(--accent-soft)", borderColor: "var(--accent)", color: "var(--accent)" }
              : { background: "var(--panel-2)", borderColor: "var(--line)" }}
            className="px-2 py-0.5 rounded border text-xs">
            {d.name}
          </button>
        ))}
        {datasets.length === 0 && <span className="text-gray-400">no datasets visible</span>}
      </div>
    </div>
  );
}
