"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { getAISettings, providerLabel } from "@/lib/aiSettings";
import type { AiSqlResponse, Dataset, SqlRunResponse } from "@/lib/types";
import type { SavedQuery } from "@/lib/dashboards";
import { ResourceHeader, ResourceToolbar } from "@/components/foundry/FoundryPrimitives";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

const PROVIDERS = ["ollama", "gemini", "openai_compatible"];

export default function SqlPage() {
  const [queryId, setQueryId] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [question, setQuestion] = useState("show me a count of rows in each table");
  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState("");
  const [sql, setSql] = useState("SELECT 1;");
  const [explanation, setExplanation] = useState<string>("");
  const [result, setResult] = useState<SqlRunResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedQuery[]>([]);
  const [queryName, setQueryName] = useState("Untitled query");
  const [openedQueryId, setOpenedQueryId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("Code");
  const [runPhase, setRunPhase] = useState<string | null>(null);
  const [resolvedSql, setResolvedSql] = useState("");
  const [activeQueryId, setActiveQueryId] = useState<string | null>(null);

  useEffect(() => {
    setQueryId(new URLSearchParams(window.location.search).get("query"));
    const ai = getAISettings();
    setProvider(ai.provider);
    setModel(ai.model);
  }, []);

  useEffect(() => {
    apiFetch<Dataset[]>("/catalog/datasets").then(setDatasets).catch((e) => setError(e.message));
    apiFetch<SavedQuery[]>("/dashboards/saved-queries").then((rows) => {
      setSaved(rows);
      const opened = rows.find((q) => q.id === queryId);
      if (opened) {
        setSql(opened.sql);
        setQueryName(opened.name);
        setSelected(new Set(opened.dataset_ids));
        setOpenedQueryId(opened.id);
      }
    }).catch(() => undefined);
  }, [queryId]);

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelected(next);
  }

  async function generate() {
    setBusy(true); setError(null);
    try {
      const res = await apiFetch<AiSqlResponse>("/ai/sql", {
        method: "POST",
        body: JSON.stringify({
          question,
          provider,
          model: model.trim() || null,
          dataset_ids: selected.size > 0 ? Array.from(selected) : null,
        }),
      });
      setSql(res.sql);
      setExplanation(res.explanation);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  async function run() {
    const nextQueryId =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`;
    setActiveQueryId(nextQueryId);
    setBusy(true); setError(null);
    try {
      const ids = selected.size > 0 ? Array.from(selected) : datasets.map((d) => d.id);
      const res = await apiFetch<SqlRunResponse>("/ai/run-sql", {
        method: "POST",
        body: JSON.stringify({ sql, dataset_ids: ids, query_id: nextQueryId }),
      });
      setResult(res);
      setRunPhase(res.phase ?? "engine_execution");
      setResolvedSql(res.resolved_sql ?? "");
      setActiveTab("Results");
    } catch (e: unknown) {
      const raw = e instanceof Error ? e.message : String(e);
      try {
        const detail = JSON.parse(raw);
        setRunPhase(detail.phase ?? "execution");
        setResolvedSql(detail.resolved_sql ?? "");
        setError(`${detail.phase ?? "execution"}: ${detail.code ?? "failed"} - ${detail.message ?? raw}`);
      } catch {
        setRunPhase("execution");
        setError(raw);
      }
    } finally { setBusy(false); setActiveQueryId(null); }
  }

  async function cancelRun() {
    if (!activeQueryId) return;
    try {
      await apiFetch(`/queries/${encodeURIComponent(activeQueryId)}/cancel`, { method: "POST" });
      setError("Cancel requested");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function saveQuery() {
    setBusy(true); setError(null);
    try {
      const q = await apiFetch<SavedQuery>(openedQueryId ? `/dashboards/saved-queries/${openedQueryId}` : "/dashboards/saved-queries", {
        method: openedQueryId ? "PUT" : "POST",
        body: JSON.stringify({ name: queryName, sql, dataset_ids: selected.size > 0 ? Array.from(selected) : [] }),
      });
      setOpenedQueryId(q.id);
      setSaved((prev) => [q, ...prev.filter((x) => x.id !== q.id)]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  async function deleteQuery(id: string) {
    if (!confirm("Delete saved query?")) return;
    await apiFetch(`/dashboards/saved-queries/${id}`, { method: "DELETE" });
    setSaved((prev) => prev.filter((q) => q.id !== id));
  }

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <ResourceHeader
        eyebrow="SQL Preview"
        title={queryName || "SQL"}
        subtitle="Query governed datasets, generate SQL with the configured AI provider, save reusable SQL files, and inspect results in a Foundry-style workbench."
        tabs={[{ label: "Code", id: "Code" }, { label: "History", id: "History" }, { label: "Results", id: "Results" }]}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        actions={
          <>
            <button className="btn-ghost" onClick={saveQuery} disabled={busy}>Save query</button>
            {activeQueryId ? <button className="btn-ghost" onClick={cancelRun} type="button">Cancel</button> : null}
            <button className="btn-primary" onClick={run} disabled={busy}>{busy ? "Running..." : "Run"}</button>
          </>
        }
      />
      <ResourceToolbar>
        <button className="btn-ghost">Reset</button>
        <button className="btn-ghost" onClick={() => navigator.clipboard?.writeText(sql)}>Copy</button>
        <button className="btn-ghost" onClick={generate} disabled={busy}>AI generate</button>
        <span className="badge">{selected.size || datasets.length} datasets</span>
        {result ? <span className="badge badge-success">{result.row_count} rows</span> : null}
        {error ? <span className="badge badge-danger">{error}</span> : null}
      </ResourceToolbar>
      {activeTab === "History" ? (
        <main className="app-card" style={{ padding: 12 }}>
          <div className="panel-heading" style={{ padding: "0 0 8px", border: 0 }}>Saved query history</div>
          <div style={{ display: "grid", gap: 8 }}>
            {saved.map((q) => <button key={q.id} type="button" className="btn-ghost" onClick={() => { setSql(q.sql); setQueryName(q.name); setSelected(new Set(q.dataset_ids)); setOpenedQueryId(q.id); setActiveTab("Code"); }}>{q.name}</button>)}
            {!saved.length ? <div className="empty-state"><div className="empty-state-title">No saved SQL yet.</div></div> : null}
          </div>
        </main>
      ) : activeTab === "Results" ? (
        <main className="app-card" style={{ padding: 0, overflow: "auto", minHeight: 420 }}>
          <div className="panel-heading">Results {runPhase ? <span className="badge">{runPhase}</span> : null}</div>
          {resolvedSql ? <pre style={{ margin: 12, padding: 10, background: "#f7f9fc", overflow: "auto" }}>{resolvedSql}</pre> : null}
          {result ? (
            <table className="w-full text-xs">
              <thead><tr>{result.columns.map((c) => <th key={c} className="px-3 py-2 text-left">{c}</th>)}</tr></thead>
              <tbody>{result.rows.map((r, i) => <tr key={i}>{result.columns.map((c) => <td key={c} className="px-3 py-1 font-mono">{String(r[c] ?? "")}</td>)}</tr>)}</tbody>
            </table>
          ) : <div className="empty-state"><div className="empty-state-title">No results yet.</div></div>}
        </main>
      ) : (
      <div className="grid grid-cols-12 gap-4" style={{ minHeight: "calc(100vh - 230px)" }}>
      <aside className="col-span-3 app-card overflow-auto" style={{ padding: 14 }}>
        <h2 className="font-semibold mb-2">AI</h2>
        <select className="input-dark mb-3" value={provider} onChange={(e) => setProvider(e.target.value)}>
          {PROVIDERS.map((p) => <option key={p} value={p}>{providerLabel(p)}</option>)}
        </select>
        <input className="input-dark mb-3" value={model} onChange={(e) => setModel(e.target.value)} placeholder="Model override" />
        <textarea
          className="input-dark mb-2"
          style={{ height: 128, resize: "vertical" }}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button onClick={generate} disabled={busy} className="w-full btn-primary disabled:opacity-50">
          {busy ? "..." : "Generate SQL"}
        </button>
        {explanation && <p className="mt-3 text-xs" style={{ color: "var(--muted)" }}>{explanation}</p>}

        <h2 className="font-semibold mt-6 mb-2">Datasets</h2>
        <div className="space-y-1 text-sm">
          {datasets.map((d) => (
            <label key={d.id} className="flex gap-2 items-center">
              <input type="checkbox" checked={selected.has(d.id)} onChange={() => toggle(d.id)} />
              <span className="truncate">{d.name}</span>
            </label>
          ))}
          {datasets.length === 0 && <div className="text-xs" style={{ color: "var(--muted)" }}>No datasets visible.</div>}
        </div>
      </aside>

      <section className="col-span-6 flex flex-col gap-3">
        <div className="app-card overflow-hidden" style={{ display: "grid", gridTemplateRows: "42px 1fr", minHeight: 460, padding: 0 }}>
          <div className="border-b px-3 py-2 flex items-center gap-2" style={{ borderColor: "var(--line)" }}>
            <input value={queryName} onChange={(e) => setQueryName(e.target.value)} style={{ flex: 1, padding: "5px 8px", fontWeight: 650 }} />
            <span className="badge">{openedQueryId ? "Saved SQL file" : "Unsaved SQL"}</span>
            <button className="btn-ghost" onClick={saveQuery} disabled={busy}>Save query</button>
          </div>
          <MonacoEditor
            language="sql"
            theme="vs-light"
            value={sql}
            onChange={(v) => setSql(v ?? "")}
            options={{ minimap: { enabled: false }, fontSize: 13 }}
          />
        </div>
        <div className="flex items-center gap-2">
          <button onClick={run} disabled={busy}
            className="btn-primary disabled:opacity-50">
            {busy ? "Running..." : "Run"}
          </button>
          {activeQueryId ? (
            <button onClick={cancelRun} type="button" className="btn-ghost">
              Cancel
            </button>
          ) : null}
          {result && (
            <span className="text-xs" style={{ color: "var(--muted)" }}>
              {result.row_count} rows {result.cached ? "(cached)" : ""}
            </span>
          )}
          {error && <span className="text-xs" style={{ color: "var(--danger)" }}>{error}</span>}
        </div>
        <div className="app-card flex-1 overflow-auto" style={{ padding: 0 }}>
          {result ? (
            <table className="w-full text-xs">
              <thead className="sticky top-0">
                <tr>{result.columns.map((c) => <th key={c} className="px-3 py-2 text-left">{c}</th>)}</tr>
              </thead>
              <tbody>
                {result.rows.map((r, i) => (
                  <tr key={i} className="border-t">
                    {result.columns.map((c) => (
                      <td key={c} className="px-3 py-1 font-mono">{String(r[c] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-4 text-sm" style={{ color: "var(--muted)" }}>Run a query to see results.</div>
          )}
        </div>
      </section>

      <aside className="col-span-3 app-card overflow-auto" style={{ padding: 14 }}>
        <h2 className="font-semibold mb-2">Saved queries</h2>
        <input className="w-full px-2 py-1 text-sm mb-2" value={queryName} onChange={(e) => setQueryName(e.target.value)} />
        <button onClick={saveQuery} disabled={busy} className="btn-primary w-full justify-center mb-3">Save current SQL</button>
        <div className="space-y-2">
          {saved.map((q) => (
            <div key={q.id} className="app-card" style={{ padding: 8 }}>
              <button type="button" onClick={() => { setSql(q.sql); setQueryName(q.name); setSelected(new Set(q.dataset_ids)); setOpenedQueryId(q.id); }} className="text-left w-full">
                <div className="font-semibold text-sm">{q.name}</div>
                <div className="font-mono text-xs truncate" style={{ color: "var(--muted)" }}>{q.sql}</div>
              </button>
              <button type="button" className="text-xs mt-2" style={{ color: "var(--danger)", background: "transparent", border: 0, padding: 0 }} onClick={() => deleteQuery(q.id)}>Delete</button>
            </div>
          ))}
          {saved.length === 0 && <div className="text-xs" style={{ color: "var(--muted)" }}>No saved queries.</div>}
        </div>
      </aside>
      </div>
      )}
    </div>
  );
}
