"use client";

import { useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { ErrorState } from "@/components/platform/States";
import { aiApi, type AIProvider, type SqlDraft } from "@/lib/api/endpoints/ai";
import { ApiError } from "@/lib/api";

export default function AiAssistantPage() {
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [datasets, setDatasets] = useState<{ id: string; name: string }[]>([]);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [selectedDatasets, setSelectedDatasets] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [draft, setDraft] = useState<SqlDraft | null>(null);
  const [result, setResult] = useState<{ columns?: string[]; rows?: Record<string, unknown>[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, d] = await Promise.all([aiApi.providers(), aiApi.datasets()]);
      setProviders(p);
      setDatasets(d);
      setProvider((cur) => cur || p.find((x) => x.configured)?.name || p[0]?.name || "");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load providers.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleDraft() {
    if (!question.trim() || !provider) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setDraft(await aiApi.draftSql({ question: question.trim(), provider, model: model.trim() || null, dataset_ids: selectedDatasets }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to draft SQL.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRun() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      const res = await aiApi.runSql({ sql: draft.sql, dataset_ids: selectedDatasets });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to run SQL.");
    } finally {
      setBusy(false);
    }
  }

  function toggleDataset(id: string) {
    setSelectedDatasets((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="AI assistant" type="AI" subtitle="Ask a question, review the governed SQL draft, then run it." />
      {error ? <ErrorState message={error} /> : null}

      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="app-card space-y-3 p-4">
          <label className="block text-xs font-medium text-[var(--muted)]">
            Provider
            <select className="input-dark mt-1 w-full" value={provider} onChange={(e) => setProvider(e.target.value)}>
              {providers.map((p) => (
                <option key={p.name} value={p.name}>{p.label}{p.configured ? "" : " (not configured)"}</option>
              ))}
            </select>
          </label>
          <label className="block text-xs font-medium text-[var(--muted)]">
            Model (optional override)
            <input className="input-dark mt-1 w-full" value={model} onChange={(e) => setModel(e.target.value)} placeholder="default" />
          </label>
          <div className="text-xs font-medium text-[var(--muted)]">
            Datasets
            <div className="mt-1 max-h-48 space-y-1 overflow-y-auto rounded border border-[var(--line-soft)] p-2">
              {datasets.map((d) => (
                <label key={d.id} className="flex items-center gap-2 text-sm text-[var(--text)]">
                  <input type="checkbox" checked={selectedDatasets.includes(d.id)} onChange={() => toggleDataset(d.id)} />
                  {d.name}
                </label>
              ))}
              {!datasets.length ? <p className="text-xs text-[var(--muted)]">No datasets available.</p> : null}
            </div>
          </div>
        </aside>

        <section className="space-y-4">
          <div className="app-card space-y-3 p-4">
            <label className="block text-xs font-medium text-[var(--muted)]">
              Question
              <textarea className="input-dark mt-1 min-h-24 w-full" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Top 10 customers by revenue this year" />
            </label>
            <button type="button" className="toolbar-button" onClick={() => void handleDraft()} disabled={busy || !question.trim() || !provider}>
              {busy ? "Working..." : "Draft SQL"}
            </button>
          </div>

          {draft ? (
            <div className="app-card space-y-3 p-4">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Generated SQL</h2>
                <span className="text-xs text-[var(--muted)]">confidence: {String(draft.confidence)}</span>
              </div>
              <pre className="overflow-x-auto rounded bg-black/20 p-3 text-xs">{draft.sql}</pre>
              {draft.explanation ? <p className="text-sm text-[var(--muted)]">{draft.explanation}</p> : null}
              <button type="button" className="btn-primary" onClick={() => void handleRun()} disabled={busy}>
                {busy ? "Running..." : "Run governed query"}
              </button>
            </div>
          ) : null}

          {result?.columns ? (
            <div className="app-card overflow-x-auto p-0">
              <table className="w-full text-left text-sm">
                <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                  <tr>{result.columns.map((c) => <th key={c} className="px-3 py-2">{c}</th>)}</tr>
                </thead>
                <tbody>
                  {(result.rows || []).slice(0, 100).map((row, i) => (
                    <tr key={i} className="border-t border-[var(--line-soft)]">
                      {result.columns!.map((c) => <td key={c} className="px-3 py-2">{String(row[c] ?? "")}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
