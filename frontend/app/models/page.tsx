"use client";

import { useEffect, useState, type ReactNode } from "react";
import { apiFetch } from "@/lib/api";
import type { Dataset } from "@/lib/types";
import type { MLModel, MLModelDetail, MLModelVersion } from "@/lib/models";
import { BottomDrawer, ResourceHeader, ResourceToolbar } from "@/components/foundry/FoundryPrimitives";

export default function ModelsPage() {
  const [models, setModels] = useState<MLModel[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selected, setSelected] = useState<MLModel | null>(null);
  const [versions, setVersions] = useState<MLModelVersion[]>([]);
  const [detail, setDetail] = useState<MLModelDetail | null>(null);
  const [activeTab, setActiveTab] = useState("Overview");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "Untitled model",
    description: "",
    task_type: "regression",
    input_dataset_id: "",
    target_column: "",
    feature_columns: "",
  });

  async function load() {
    const [ms, ds] = await Promise.all([
      apiFetch<MLModel[]>("/models"),
      apiFetch<Dataset[]>("/catalog/datasets"),
    ]);
    setModels(ms);
    setDatasets(ds);
    if (!selected && ms[0]) setSelected(ms[0]);
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) {
      setVersions([]);
      setDetail(null);
      return;
    }
    apiFetch<MLModelVersion[]>(`/models/${selected.id}/versions`).then(setVersions).catch(() => setVersions([]));
    apiFetch<MLModelDetail>(`/models/${selected.id}/detail`).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  async function createModel() {
    setBusy(true); setError(null);
    try {
      const created = await apiFetch<MLModel>("/models", {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          description: form.description || null,
          task_type: form.task_type,
          model_type: "baseline",
          input_dataset_id: form.input_dataset_id,
          target_column: form.target_column,
          feature_columns: form.feature_columns.split(",").map((s) => s.trim()).filter(Boolean),
        }),
      });
      setModels((prev) => [created, ...prev]);
      setSelected(created);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "create failed");
    } finally {
      setBusy(false);
    }
  }

  async function train() {
    if (!selected) return;
    setBusy(true); setError(null);
    try {
      const v = await apiFetch<MLModelVersion>(`/models/${selected.id}/train`, { method: "POST" });
      setVersions((prev) => [v, ...prev]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "train failed");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!selected || !confirm("Delete this model?")) return;
    await apiFetch(`/models/${selected.id}`, { method: "DELETE" });
    setSelected(null);
    await load();
  }

  const selectedDataset = datasets.find((d) => d.id === selected?.input_dataset_id) ?? null;
  const latestVersion = versions[0] ?? null;

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <ResourceHeader
        eyebrow="Models"
        title={selected?.name ?? "Model Management"}
        subtitle={selected?.description ?? "Train, version, inspect, and operationalize tabular models for pipeline inference."}
        tabs={[{ label: "Overview", id: "Overview" }, { label: "Versions", id: "Versions" }, { label: "Build info", id: "Build info" }, { label: "Usage", id: "Usage" }]}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        actions={selected ? (
          <>
            <button className="btn-primary" onClick={train} disabled={busy}>Train</button>
            <button className="btn-ghost" onClick={remove}>Delete</button>
          </>
        ) : null}
      />
      <ResourceToolbar>
        <button className="btn-ghost">Feature set</button>
        <button className="btn-ghost">Evaluate</button>
        <button className="btn-ghost">Deploy to pipeline</button>
        <LinkOrSpan href={latestVersion?.job_id ? "/builds" : undefined}>Open build</LinkOrSpan>
        {latestVersion ? <span className="badge badge-accent">v{latestVersion.version} · {latestVersion.status}</span> : <span className="badge">No versions</span>}
      </ResourceToolbar>
      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr 360px", gap: 12, minHeight: "calc(100vh - 260px)" }}>
      <aside className="app-card" style={{ padding: 0, overflow: "hidden" }}>
        <div className="panel-heading">Models</div>
        {models.map((m) => (
          <button
            key={m.id}
            type="button"
            onClick={() => setSelected(m)}
            style={{
              display: "block", width: "100%", textAlign: "left", padding: "10px 12px",
              border: 0, borderBottom: "1px solid var(--line-soft)",
              background: selected?.id === m.id ? "var(--accent-soft)" : "transparent",
            }}
          >
            <div style={{ fontWeight: 650 }}>{m.name}</div>
            <div style={{ color: "var(--muted)", fontSize: 11 }}>{m.task_type} · {m.feature_columns.length} features</div>
          </button>
        ))}
      </aside>

      <main className="app-card" style={{ padding: 14 }}>
        {error ? <div style={{ color: "var(--danger)", fontSize: 12 }}>{error}</div> : null}
        <div className="foundry-grid" style={{ marginBottom: 12 }}>
          <section className="app-card" style={{ padding: 14 }}>
            <div className="stat-label">Input dataset</div>
            <div className="stat-value">{selectedDataset?.name ?? "Not selected"}</div>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>{selectedDataset ? `${selectedDataset.schema_name}.${selectedDataset.table_name}` : "Choose a dataset in the form"}</div>
          </section>
          <section className="app-card" style={{ padding: 14 }}>
            <div className="stat-label">Target</div>
            <div className="stat-value">{selected?.target_column ?? "--"}</div>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>{selected?.feature_columns.length ?? 0} feature columns</div>
          </section>
          <section className="app-card" style={{ padding: 14 }}>
            <div className="stat-label">Latest build</div>
            <div className="stat-value">{latestVersion ? `v${latestVersion.version}` : "--"}</div>
            <div style={{ color: "var(--muted)", fontSize: 12 }}>{latestVersion?.status ?? "No training run yet"}</div>
          </section>
        </div>
        {activeTab === "Overview" ? (
          <div style={{ display: "grid", gap: 10 }}>
            <div><b>Latest metrics</b></div>
            <pre>{JSON.stringify(detail?.latest_metrics ?? latestVersion?.metrics ?? {}, null, 2)}</pre>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {(detail?.feature_metadata ?? []).filter((c) => c.role !== "available").map((c) => <span key={String(c.name)} className="badge">{String(c.name)} · {String(c.data_type ?? "unknown")} · {String(c.role)}</span>)}
            </div>
          </div>
        ) : activeTab === "Versions" ? (
          <table className="data-table">
          <thead><tr><th>Version</th><th>Status</th><th>Metrics</th><th>Job</th></tr></thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.id}>
                <td>v{v.version}</td>
                <td><span className="badge">{v.status}</span></td>
                <td className="font-mono" style={{ fontSize: 11 }}>{JSON.stringify(v.metrics ?? {})}</td>
                <td>{v.job_id ? <a className="text-blue-400" href={`/admin/jobs`}>{v.job_id.slice(0, 8)}</a> : "--"}</td>
              </tr>
            ))}
          </tbody>
          </table>
        ) : activeTab === "Build info" ? (
          <pre>{JSON.stringify({ build_job: detail?.build_job, artifact_path: latestVersion?.artifact_path, latest_metrics: detail?.latest_metrics }, null, 2)}</pre>
        ) : (
          <div className="empty-state"><div className="empty-state-title">Usage is not connected yet.</div><div className="empty-state-help">Pipeline inference and API usage will appear here when backend usage data is available.</div></div>
        )}
      </main>

      <aside className="app-card" style={{ padding: 14, display: "grid", gap: 10, alignContent: "start" }}>
        <div className="panel-heading" style={{ padding: 0, border: 0 }}>New model</div>
        <input className="input-dark" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Name" />
        <textarea className="input-dark" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Description" rows={3} />
        <select className="input-dark" value={form.task_type} onChange={(e) => setForm({ ...form, task_type: e.target.value })}>
          <option value="regression">Regression</option>
          <option value="classification">Classification</option>
        </select>
        <select className="input-dark" value={form.input_dataset_id} onChange={(e) => setForm({ ...form, input_dataset_id: e.target.value })}>
          <option value="">Pick dataset</option>
          {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <input className="input-dark font-mono" value={form.target_column} onChange={(e) => setForm({ ...form, target_column: e.target.value })} placeholder="target_column" />
        <input className="input-dark font-mono" value={form.feature_columns} onChange={(e) => setForm({ ...form, feature_columns: e.target.value })} placeholder="feature_a, feature_b" />
        <button className="btn-primary" onClick={createModel} disabled={busy}>Create model</button>
      </aside>
      </div>
      <BottomDrawer title="Build info" tabs={["Build progress", "Metrics", "Logs", "Spark details"]} active="Build progress">
        {latestVersion ? (
          <div style={{ display: "grid", gap: 10 }}>
            <div className="stat-row">
              <span>Status: {latestVersion.status}</span><span className="dot">•</span>
              <span>Version: v{latestVersion.version}</span><span className="dot">•</span>
              <span>Job: {latestVersion.job_id?.slice(0, 8) ?? "--"}</span>
            </div>
            <div style={{ height: 14, background: "var(--line-soft)", position: "relative" }}>
              <div style={{ position: "absolute", inset: 0, width: latestVersion.status === "succeeded" ? "100%" : "45%", background: latestVersion.status === "failed" ? "var(--danger)" : "var(--success)" }} />
            </div>
            <pre>{JSON.stringify(latestVersion.metrics ?? latestVersion.training_config ?? {}, null, 2)}</pre>
          </div>
        ) : <div style={{ color: "var(--muted)" }}>Train a model to create build information.</div>}
      </BottomDrawer>
    </div>
  );
}

function LinkOrSpan({ href, children }: { href?: string; children: ReactNode }) {
  if (!href) return <span className="badge">{children}</span>;
  return <a className="btn-ghost" href={href}>{children}</a>;
}
