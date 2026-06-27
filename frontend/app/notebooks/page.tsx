"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { NotebookDetail, NotebookSummary } from "@/lib/notebooks";
import type { ResourceActivity } from "@/lib/types";
import { ModuleCard, ResourceHeader } from "@/components/foundry/FoundryPrimitives";

export default function CodeWorkspacesPage() {
  const [items, setItems] = useState<NotebookSummary[]>([]);
  const [recents, setRecents] = useState<ResourceActivity[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const [notebooks, recentRows] = await Promise.all([
      apiFetch<NotebookSummary[]>("/notebooks"),
      apiFetch<ResourceActivity[]>("/activity/recents?limit=12").catch(() => []),
    ]);
    setItems(notebooks);
    setRecents(recentRows.filter((r) => r.resource_type === "notebook"));
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  async function createNotebook(kind: "python" | "sql") {
    const title = prompt("Workspace name", kind === "python" ? "Python Code Workspace" : "SQL Code Workspace");
    if (!title) return;
    const nb = await apiFetch<NotebookDetail>("/notebooks", {
      method: "POST",
      body: JSON.stringify({
        title,
        notebook_kind: kind,
        ai_policy: "local_only",
        kernel_name: kind === "python" ? "Python 3 (ipykernel)" : "SQL",
        requirements: kind === "python" ? ["pandas", "numpy", "matplotlib"] : [],
        workspace_metadata: { experience: "jupyterlab_like" },
      }),
    });
    window.location.href = `/notebooks/${nb.id}`;
  }

  async function remove(id: string) {
    if (!confirm("Delete this code workspace?")) return;
    await apiFetch(`/notebooks/${id}`, { method: "DELETE" });
    setItems((prev) => prev.filter((n) => n.id !== id));
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <ResourceHeader
        eyebrow="Code Workspaces"
        title="Jupyter-Style Analysis Workspaces"
        subtitle="Explore data with Python or SQL notebooks, package metadata, model context, and sandboxed execution."
        tabs={[{ label: "Data", id: "Data" }, { label: "Packages", id: "Packages" }, { label: "Dashboards", id: "Dashboards" }, { label: "Models", id: "Models" }]}
        activeTab="Data"
        actions={
          <>
            <button className="btn-ghost" onClick={() => createNotebook("sql")}>New SQL workspace</button>
            <button className="btn-primary" onClick={() => createNotebook("python")}>New Python workspace</button>
          </>
        }
      />
      {error ? <div className="app-card" style={{ padding: 12, color: "var(--danger)" }}>Load failed: {error}</div> : null}

      <div className="foundry-grid">
        <button onClick={() => createNotebook("python")} style={{ textAlign: "left", border: 0, background: "transparent", padding: 0 }}>
          <ModuleCard title="Python notebook" subtitle="Run Python cells, inspect tables, and visualize outputs in a Jupyter-like surface." icon="py" />
        </button>
        <button onClick={() => createNotebook("sql")} style={{ textAlign: "left", border: 0, background: "transparent", padding: 0 }}>
          <ModuleCard title="SQL notebook" subtitle="Iterate over datasets with SQL cells and reusable outputs." icon="SQL" />
        </button>
        <Link href="/code-repo" style={{ textDecoration: "none", color: "inherit" }}>
          <ModuleCard title="Production repository" subtitle="Move stable notebook logic into reviewable code repositories." icon="git" />
        </Link>
      </div>

      <div className="foundry-workbench">
        <section className="app-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="section-header">
            <div className="section-header-title">Workspaces</div>
            <span className="badge">{items.length}</span>
          </div>
          <table>
            <thead><tr><th>Title</th><th>Kernel</th><th>Packages</th><th>Updated</th><th></th></tr></thead>
            <tbody>
              {items.map((n) => (
                <tr key={n.id}>
                  <td><Link href={`/notebooks/${n.id}`} className="text-blue-600">{n.title}</Link><div style={{ color: "var(--muted)", fontSize: 12 }}>{n.description}</div></td>
                  <td><span className="badge">{n.kernel_name ?? n.notebook_kind}</span></td>
                  <td>{(n.requirements ?? []).slice(0, 3).map((r) => <span key={r} className="badge" style={{ marginRight: 4 }}>{r}</span>)}</td>
                  <td>{new Date(n.updated_at).toLocaleString()}</td>
                  <td style={{ textAlign: "right" }}><button className="btn-ghost" onClick={() => remove(n.id)}>Delete</button></td>
                </tr>
              ))}
              {!items.length ? <tr><td colSpan={5}><div className="empty-state"><div className="empty-state-title">No code workspaces yet</div></div></td></tr> : null}
            </tbody>
          </table>
        </section>
        <aside className="app-card" style={{ padding: 0 }}>
          <div className="panel-heading">Recent</div>
          <div style={{ padding: 12, display: "grid", gap: 8 }}>
            {recents.map((r) => <Link key={r.id} className="btn-ghost" href={r.path ?? `/notebooks/${r.resource_id}`}>{r.title}</Link>)}
            {!recents.length ? <div style={{ color: "var(--muted)" }}>Open a workspace to populate recent notebooks.</div> : null}
          </div>
        </aside>
      </div>
    </div>
  );
}
