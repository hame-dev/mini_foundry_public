"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { ConfirmDialog } from "@/components/foundry";
import { aiApi, type AiEvaluation } from "@/lib/api/endpoints/ai";
import { ApiError } from "@/lib/api";

export default function AiEvaluationsPage() {
  const [evals, setEvals] = useState<AiEvaluation[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AiEvaluation | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setEvals(await aiApi.listEvaluations());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load evaluations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await aiApi.createEvaluation({ name: name.trim(), description: description.trim() || null, provider: provider.trim() || null, model: model.trim() || null });
      setName("");
      setDescription("");
      setProvider("");
      setModel("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create evaluation.");
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setDeleteTarget(null);
    try {
      await aiApi.deleteEvaluation(target.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to delete evaluation.");
    }
  }

  async function runEvaluation(id: string) {
    setRunningId(id);
    setError(null);
    try {
      await aiApi.runEvaluation(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to run evaluation.");
    } finally {
      setRunningId(null);
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Evaluations" type="AI" status={`${evals.length} evaluations`} />
      {loading ? <LoadingState label="Loading evaluations..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="font-semibold">Evaluation registry</h2>
              <p className="text-sm text-[var(--muted)]">Recorded AI evaluations and their results. (Running evals against live providers is a future step.)</p>
            </div>
            {evals.length ? (
              <table className="w-full text-left text-sm">
                <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                  <tr>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Model</th>
                    <th className="px-4 py-3">Score</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {evals.map((e) => (
                    <tr key={e.id} className="border-t border-[var(--line-soft)]">
                      <td className="px-4 py-3 font-medium">{e.name}</td>
                      <td className="px-4 py-3 text-xs">{e.provider || "—"} / {e.model || "—"}</td>
                      <td className="px-4 py-3">{e.score != null ? e.score.toFixed(2) : "—"}</td>
                      <td className="px-4 py-3 text-xs">{e.status}</td>
                      <td className="px-4 py-3 text-right">
                        <button type="button" className="toolbar-button mr-2" onClick={() => void runEvaluation(e.id)} disabled={runningId === e.id}>
                          {runningId === e.id ? "Running" : "Run"}
                        </button>
                        <button type="button" className="toolbar-button" onClick={() => setDeleteTarget(e)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-4"><EmptyState title="No evaluations" detail="Record an evaluation to track AI quality over time." /></div>
            )}
          </section>

          <aside>
            <form className="app-card space-y-3 p-4" onSubmit={handleCreate}>
              <h2 className="font-semibold">New evaluation</h2>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Name
                <input className="input-dark mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Description
                <input className="input-dark mt-1 w-full" value={description} onChange={(e) => setDescription(e.target.value)} />
              </label>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Provider
                <input className="input-dark mt-1 w-full" value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="ollama" />
              </label>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Model
                <input className="input-dark mt-1 w-full" value={model} onChange={(e) => setModel(e.target.value)} />
              </label>
              <button type="submit" className="toolbar-button w-full justify-center" disabled={saving || !name.trim()}>
                {saving ? "Saving" : "Create evaluation"}
              </button>
            </form>
          </aside>
        </div>
      ) : null}

      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDelete()}
        title="Delete evaluation"
        message={`Delete evaluation "${deleteTarget?.name}"?`}
        confirmLabel="Delete"
        danger
      />
    </div>
  );
}
