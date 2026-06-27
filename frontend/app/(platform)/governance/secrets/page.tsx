"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { ConfirmDialog } from "@/components/foundry";
import { createSecret, deleteSecret, listSecrets, Secret } from "@/lib/governance";
import { ApiError } from "@/lib/api";

export default function GovernanceSecretsPage() {
  const [secrets, setSecrets] = useState<Secret[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Secret | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [value, setValue] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSecrets(await listSecrets());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load secrets.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || !value) return;
    setSaving(true);
    setError(null);
    try {
      await createSecret({ name: name.trim(), description: description.trim() || null, value });
      setName("");
      setDescription("");
      setValue("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create secret.");
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setDeleteTarget(null);
    setError(null);
    try {
      await deleteSecret(target.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to delete secret.");
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Secrets" type="Governance" status={`${secrets.length} secrets`} />
      {loading ? <LoadingState label="Loading secrets..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="font-semibold">Stored secrets</h2>
              <p className="text-sm text-[var(--muted)]">Values are encrypted at rest and never displayed after creation.</p>
            </div>
            {secrets.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                    <tr>
                      <th className="px-4 py-3">Name</th>
                      <th className="px-4 py-3">Description</th>
                      <th className="px-4 py-3">Created</th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody>
                    {secrets.map((s) => (
                      <tr key={s.id} className="border-t border-[var(--line-soft)]">
                        <td className="px-4 py-3 font-medium">{s.name || s.id.slice(0, 8)}</td>
                        <td className="px-4 py-3 text-[var(--muted)]">{s.description || "—"}</td>
                        <td className="px-4 py-3 text-[var(--muted)]">{new Date(s.created_at).toLocaleString()}</td>
                        <td className="px-4 py-3 text-right">
                          <button type="button" className="toolbar-button" onClick={() => setDeleteTarget(s)}>Delete</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-4"><EmptyState title="No secrets" detail="Create a secret to reference from connectors and integrations." /></div>
            )}
          </section>

          <aside>
            <form className="app-card space-y-3 p-4" onSubmit={handleCreate}>
              <h2 className="font-semibold">Create secret</h2>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Name
                <input className="input-dark mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Description
                <input className="input-dark mt-1 w-full" value={description} onChange={(e) => setDescription(e.target.value)} />
              </label>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Value (write-only)
                <input type="password" className="input-dark mt-1 w-full" value={value} onChange={(e) => setValue(e.target.value)} autoComplete="new-password" />
              </label>
              <button type="submit" className="toolbar-button w-full justify-center" disabled={saving || !name.trim() || !value}>
                {saving ? "Saving" : "Create secret"}
              </button>
            </form>
          </aside>
        </div>
      ) : null}

      <ConfirmDialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDelete()}
        title="Delete secret"
        message={`Delete secret "${deleteTarget?.name || deleteTarget?.id}"? Anything referencing it will stop working.`}
        confirmLabel="Delete"
        danger
      />
    </div>
  );
}
