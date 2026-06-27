"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { createProject, listProjects, type Project } from "@/lib/projects";
import { ApiError } from "@/lib/api";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setProjects(await listProjects());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load projects.");
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
      await createProject({ name: name.trim(), description: description.trim() || null });
      setName("");
      setDescription("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create project.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Projects" type="Workspace" status={`${projects.length} projects`} />
      {loading ? <LoadingState label="Loading projects..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="font-semibold">All projects</h2>
              <p className="text-sm text-[var(--muted)]">Projects group resources and govern access, activity, and branches.</p>
            </div>
            {projects.length ? (
              <table className="w-full text-left text-sm">
                <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                  <tr>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Description</th>
                    <th className="px-4 py-3">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map((p) => (
                    <tr key={p.id} className="border-t border-[var(--line-soft)] hover:bg-[var(--panel-2)]">
                      <td className="px-4 py-3 font-medium">
                        <Link href={`/workspace/projects/${p.id}`} className="hover:underline">{p.name}</Link>
                      </td>
                      <td className="px-4 py-3 text-[var(--muted)]">{p.description || "—"}</td>
                      <td className="px-4 py-3 text-[var(--muted)]">{new Date(p.created_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-4"><EmptyState title="No projects" detail="Create a project to organize resources." /></div>
            )}
          </section>

          <aside>
            <form className="app-card space-y-3 p-4" onSubmit={handleCreate}>
              <h2 className="font-semibold">Create project</h2>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Name
                <input className="input-dark mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Description
                <textarea className="input-dark mt-1 min-h-20 w-full" value={description} onChange={(e) => setDescription(e.target.value)} />
              </label>
              <button type="submit" className="toolbar-button w-full justify-center" disabled={saving || !name.trim()}>
                {saving ? "Saving" : "Create project"}
              </button>
            </form>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
