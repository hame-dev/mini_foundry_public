"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { ConfirmDialog } from "@/components/foundry";
import { aiApi, type PromptPreview, type PromptTemplate } from "@/lib/api/endpoints/ai";
import { ApiError } from "@/lib/api";

export default function AiPromptsPage() {
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<PromptTemplate | null>(null);
  const [preview, setPreview] = useState<PromptPreview | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [template, setTemplate] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPrompts(await aiApi.listPrompts());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load prompt templates.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || !template.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await aiApi.createPrompt({ name: name.trim(), description: description.trim() || null, template });
      setName("");
      setDescription("");
      setTemplate("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to save template.");
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setDeleteTarget(null);
    try {
      await aiApi.deletePrompt(target.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to delete template.");
    }
  }

  async function handlePreview() {
    if (!template.trim()) return;
    setPreviewing(true);
    setError(null);
    try {
      setPreview(await aiApi.previewPrompt({
        template,
        context: { question: "Revenue trend for the last 30 days", user: { email: "analyst@example.com" } },
      }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to preview template.");
    } finally {
      setPreviewing(false);
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Prompt templates" type="AI" status={`${prompts.length} templates`} />
      {loading ? <LoadingState label="Loading prompt templates..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="font-semibold">Registry</h2>
              <p className="text-sm text-[var(--muted)]">Versioned, reusable AI prompt templates. Re-saving a name bumps its version.</p>
            </div>
            {prompts.length ? (
              <table className="w-full text-left text-sm">
                <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                  <tr>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Version</th>
                    <th className="px-4 py-3">Description</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {prompts.map((p) => (
                    <tr key={p.id} className="border-t border-[var(--line-soft)]">
                      <td className="px-4 py-3 font-medium">{p.name}</td>
                      <td className="px-4 py-3">v{p.version}</td>
                      <td className="px-4 py-3 text-[var(--muted)]">{p.description || "—"}</td>
                      <td className="px-4 py-3 text-right">
                        <button type="button" className="toolbar-button" onClick={() => setDeleteTarget(p)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-4"><EmptyState title="No templates" detail="Create a prompt template to reuse across AI flows." /></div>
            )}
          </section>

          <aside>
            <form className="app-card space-y-3 p-4" onSubmit={handleCreate}>
              <h2 className="font-semibold">New template / version</h2>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Name
                <input className="input-dark mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Description
                <input className="input-dark mt-1 w-full" value={description} onChange={(e) => setDescription(e.target.value)} />
              </label>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Template
                <textarea className="input-dark mt-1 min-h-32 w-full font-mono text-xs" value={template} onChange={(e) => setTemplate(e.target.value)} placeholder="You are a helpful analyst. {{question}}" />
              </label>
              <button type="submit" className="toolbar-button w-full justify-center" disabled={saving || !name.trim() || !template.trim()}>
                {saving ? "Saving" : "Save template"}
              </button>
              <button type="button" className="toolbar-button w-full justify-center" disabled={previewing || !template.trim()} onClick={() => void handlePreview()}>
                {previewing ? "Previewing" : "Preview redaction"}
              </button>
              {preview ? (
                <div className="rounded border border-[var(--line)] bg-[var(--panel-2)] p-3">
                  <div className="mb-2 flex flex-wrap gap-2 text-xs">
                    {preview.redactions.length ? preview.redactions.map((r) => (
                      <span key={r.type} className="badge badge-warning">{r.type}: {r.count}</span>
                    )) : <span className="badge badge-success">no redactions</span>}
                  </div>
                  <pre className="max-h-44 overflow-auto whitespace-pre-wrap text-xs text-[var(--muted)]">{preview.redacted_prompt}</pre>
                  {preview.permission_notices.length ? (
                    <ul className="mt-2 space-y-1 text-xs text-amber-100">
                      {preview.permission_notices.map((notice) => <li key={notice}>{notice}</li>)}
                    </ul>
                  ) : null}
                </div>
              ) : null}
            </form>
          </aside>
        </div>
      ) : null}

      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDelete()}
        title="Delete prompt template"
        message={`Delete "${deleteTarget?.name}" v${deleteTarget?.version}?`}
        confirmLabel="Delete"
        danger
      />
    </div>
  );
}
