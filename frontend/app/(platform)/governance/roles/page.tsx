"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { createRole, deleteRole, GovernanceRole, listRoles } from "@/lib/governance";
import { ApiError } from "@/lib/api";

export default function GovernanceRolesPage() {
  const [roles, setRoles] = useState<GovernanceRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRoles(await listRoles());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load roles.");
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
      await createRole(name.trim());
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create role.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(role: GovernanceRole) {
    setError(null);
    try {
      await deleteRole(role.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to delete role.");
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Roles" type="Governance" status={`${roles.length} roles`} />
      {loading ? <LoadingState label="Loading roles..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="font-semibold">Roles</h2>
              <p className="text-sm text-[var(--muted)]">Roles are subjects for resource ACLs, row policies, and column masks.</p>
            </div>
            {roles.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                    <tr>
                      <th className="px-4 py-3">Name</th>
                      <th className="px-4 py-3">Members</th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody>
                    {roles.map((role) => (
                      <tr key={role.id} className="border-t border-[var(--line-soft)]">
                        <td className="px-4 py-3 font-medium">{role.name}</td>
                        <td className="px-4 py-3">{role.member_count}</td>
                        <td className="px-4 py-3 text-right">
                          {role.name !== "admin" ? (
                            <button type="button" className="toolbar-button" onClick={() => void handleDelete(role)}>
                              Delete
                            </button>
                          ) : (
                            <span className="text-xs text-[var(--muted)]">built-in</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-4">
                <EmptyState title="No roles" detail="Create a role to grant shared capabilities." />
              </div>
            )}
          </section>

          <aside>
            <form className="app-card space-y-3 p-4" onSubmit={handleCreate}>
              <h2 className="font-semibold">Create role</h2>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Name
                <input className="input-dark mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <button type="submit" className="toolbar-button w-full justify-center" disabled={saving || !name.trim()}>
                {saving ? "Saving" : "Create role"}
              </button>
              <p className="text-xs text-[var(--muted)]">Assign roles to users from the Users page.</p>
            </form>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
