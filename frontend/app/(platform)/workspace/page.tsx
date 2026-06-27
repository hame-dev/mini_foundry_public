"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { DashboardDetail, SavedQuery } from "@/lib/dashboards";
import type { NotebookDetail } from "@/lib/notebooks";
import type { PipelineDetail } from "@/lib/pipelines";
import type { ResourceActivity } from "@/lib/types";
import type { WorkspaceItem, WorkspacePermission } from "@/lib/workspace";
import { WORKSPACE_LABELS } from "@/lib/workspace";
import { ModuleCard, ResourceHeader } from "@/components/foundry/FoundryPrimitives";

export default function WorkspacePage() {
  const router = useRouter();
  const [folder, setFolder] = useState<string | null>(null);
  const [roots, setRoots] = useState<WorkspaceItem[]>([]);
  const [items, setItems] = useState<WorkspaceItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [perms, setPerms] = useState<WorkspacePermission[]>([]);
  const [recents, setRecents] = useState<ResourceActivity[]>([]);
  const [favorites, setFavorites] = useState<ResourceActivity[]>([]);
  const [activeTab, setActiveTab] = useState("Projects");
  const [loading, setLoading] = useState(false);

  const selected = useMemo(
    () => items.find((i) => i.id === selectedId) ?? roots.find((i) => i.id === selectedId) ?? null,
    [items, roots, selectedId],
  );

  function openFolder(id: string | null) {
    setFolder(id);
    window.history.pushState(null, "", id ? `/workspace?folder=${id}` : "/workspace");
  }

  useEffect(() => {
    setFolder(new URLSearchParams(window.location.search).get("folder"));
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    const listPath = query
      ? `/workspace/items?q=${encodeURIComponent(query)}`
      : `/workspace/items${folder ? `?parent_id=${folder}` : ""}`;
    try {
      const list = await apiFetch<WorkspaceItem[]>(listPath);
      setItems(list);
      if (!selectedId && list[0]) setSelectedId(list[0].id);
    } catch (e: any) {
      setError(e.message?.includes("timeout") ? "Workspace index is still loading. You can repair the index or try again." : e.message);
    } finally {
      setLoading(false);
    }
    apiFetch<WorkspaceItem[]>("/workspace/roots").then(setRoots).catch(() => undefined);
    apiFetch<ResourceActivity[]>("/activity/recents?limit=10").then(setRecents).catch(() => undefined);
    apiFetch<ResourceActivity[]>("/activity/favorites?limit=10").then(setFavorites).catch(() => undefined);
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folder, query]);

  useEffect(() => {
    if (!selected) {
      setPerms([]);
      return;
    }
    apiFetch<WorkspacePermission[]>(`/workspace/items/${selected.id}/permissions`).then(setPerms).catch(() => setPerms([]));
  }, [selected]);

  async function createFolder() {
    const name = prompt("Folder name", "New folder");
    if (!name) return;
    await apiFetch("/workspace/folders", { method: "POST", body: JSON.stringify({ name, parent_id: folder }) });
    await load();
  }

  async function createSql() {
    const name = prompt("SQL file name", "Untitled SQL");
    if (!name) return;
    const q = await apiFetch<SavedQuery>("/dashboards/saved-queries", {
      method: "POST",
      body: JSON.stringify({ name, sql: "SELECT 1;", dataset_ids: [], workspace_parent_id: folder }),
    });
    router.push(`/sql?query=${q.id}`);
  }

  async function createNotebook(kind: "sql" | "python") {
    const title = prompt(`${kind === "sql" ? "SQL" : "Python"} notebook name`, `Untitled ${kind} notebook`);
    if (!title) return;
    const nb = await apiFetch<NotebookDetail>("/notebooks", {
      method: "POST",
      body: JSON.stringify({ title, notebook_kind: kind, ai_policy: "local_only", workspace_parent_id: folder }),
    });
    router.push(`/notebooks/${nb.id}`);
  }

  async function createDashboard() {
    const title = prompt("Dashboard name", "Untitled dashboard");
    if (!title) return;
    const d = await apiFetch<DashboardDetail>("/dashboards", {
      method: "POST",
      body: JSON.stringify({ title, workspace_parent_id: folder }),
    });
    router.push(`/dashboards/${d.id}/edit`);
  }

  async function createPipeline() {
    const name = prompt("Pipeline name", "Untitled pipeline");
    if (!name) return;
    const p = await apiFetch<PipelineDetail>("/pipelines", {
      method: "POST",
      body: JSON.stringify({ name, workspace_parent_id: folder }),
    });
    router.push(`/pipelines/${p.id}`);
  }

  async function removeSelected() {
    if (!selected || !confirm(`Delete ${selected.name} from workspace?`)) return;
    await apiFetch(`/workspace/items/${selected.id}`, { method: "DELETE" });
    setSelectedId(null);
    await load();
  }

  async function shareEveryone() {
    if (!selected) return;
    await apiFetch(`/workspace/items/${selected.id}/permissions`, {
      method: "POST",
      body: JSON.stringify({ subject_type: "everyone", can_view: true }),
    });
    setPerms(await apiFetch<WorkspacePermission[]>(`/workspace/items/${selected.id}/permissions`));
  }

  async function renameSelected() {
    if (!selected) return;
    const name = prompt("Rename", selected.name);
    if (!name || name === selected.name) return;
    await apiFetch(`/workspace/items/${selected.id}`, { method: "PATCH", body: JSON.stringify({ name }) });
    await load();
  }

  return (
    <div style={{ display: "grid", gridTemplateRows: "auto auto 1fr", gap: 12, minHeight: "calc(100vh - 132px)" }}>
      <ResourceHeader
        eyebrow="Compass / Files"
        title="My Workspace"
        subtitle="Projects, folders, resources, datasets, code, analyses, apps, access, and recent work."
        tabs={[{ label: "Recents", id: "Recents" }, { label: "Favorites", id: "Favorites" }, { label: "Projects", id: "Projects" }]}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        actions={
          <>
          <button className="btn-ghost" onClick={createFolder}>New folder</button>
          <button className="btn-ghost" onClick={createSql}>SQL file</button>
          <button className="btn-ghost" onClick={() => createNotebook("sql")}>SQL notebook</button>
          <button className="btn-ghost" onClick={() => createNotebook("python")}>Python notebook</button>
          <button className="btn-ghost" onClick={createDashboard}>Dashboard</button>
          <button className="btn-primary" onClick={createPipeline}>Pipeline</button>
          </>
        }
      />
      <div className="foundry-grid">
        <ModuleCard title="Pipeline Builder" subtitle="Build visual transforms from selected datasets." icon="PL" />
        <ModuleCard title="Code Workspace" subtitle="Explore data with Jupyter-style Python or SQL notebooks." icon="NB" />
        <ModuleCard title="Workshop module" subtitle="Create operational apps and dashboards on ontology objects." icon="WS" />
      </div>
      {error ? <div style={{ color: "var(--danger)" }}>{error}</div> : null}
      {activeTab !== "Projects" ? (
        <main className="app-card" style={{ padding: 0 }}>
          <div className="panel-heading">{activeTab}</div>
          <div style={{ padding: 12, display: "grid", gap: 8 }}>
            {(activeTab === "Recents" ? recents : favorites).map((r) => (
              <Link key={r.id} className="btn-ghost" href={r.path ?? "#"}>{r.title}</Link>
            ))}
            {(activeTab === "Recents" ? recents : favorites).length === 0 ? (
              <div className="empty-state"><div className="empty-state-title">No {activeTab.toLowerCase()} yet.</div></div>
            ) : null}
          </div>
        </main>
      ) : (
      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr 340px", gap: 12, minHeight: 0 }}>
        <aside className="app-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="panel-heading">Folders</div>
          {roots.map((r) => (
            <button key={r.id} type="button" onClick={() => openFolder(r.id)}
              style={{ width: "100%", textAlign: "left", padding: "10px 12px", border: 0, borderBottom: "1px solid var(--line-soft)", background: folder === r.id ? "var(--accent-soft)" : "transparent" }}>
              <span className="font-mono">/</span> {r.name}
            </button>
          ))}
          <Link href="/pipelines" className="sidebar-link" style={{ margin: 8 }}>
            <span className="sidebar-link-mark">PL</span><span className="sidebar-link-label">Open Pipeline Builder</span>
          </Link>
          <div className="panel-heading">Recents</div>
          <div style={{ padding: 8, display: "grid", gap: 6 }}>
            {recents.slice(0, 5).map((r) => <Link key={r.id} className="btn-ghost" href={r.path ?? "#"}>{r.title}</Link>)}
            {!recents.length ? <span style={{ color: "var(--muted)", fontSize: 12 }}>No recent resources.</span> : null}
          </div>
        </aside>
        <main className="app-card" style={{ padding: 0, minHeight: 0, overflow: "hidden" }}>
          <div style={{ padding: 10, borderBottom: "1px solid var(--line)", display: "flex", gap: 8 }}>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search workspace..." style={{ flex: 1, padding: "7px 10px" }} />
            {folder ? <button className="btn-ghost" onClick={() => openFolder(null)}>Root</button> : null}
            {loading ? <span className="badge">Loading</span> : null}
            {error ? <button className="btn-ghost" onClick={() => apiFetch("/workspace/repair", { method: "POST" }).then(load).catch((e) => setError(e.message))}>Repair index</button> : null}
          </div>
          <div style={{ overflow: "auto", maxHeight: "calc(100vh - 240px)" }}>
            <table>
              <thead><tr><th>Name</th><th>Type</th><th>Updated</th><th>Open</th></tr></thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} onClick={() => setSelectedId(item.id)} style={{ background: selectedId === item.id ? "var(--accent-soft)" : undefined, cursor: "pointer" }}>
                    <td style={{ color: "var(--text)" }}>{item.item_type === "folder" ? "> " : ""}{item.name}</td>
                    <td><span className="badge">{WORKSPACE_LABELS[item.item_type]}</span></td>
                    <td>{new Date(item.updated_at).toLocaleString()}</td>
                    <td>{item.href ? <Link className="text-blue-600" href={item.href}>Open</Link> : "--"}</td>
                  </tr>
                ))}
                {items.length === 0 ? <tr><td colSpan={4}><div className="empty-state"><div className="empty-state-title">No files here</div></div></td></tr> : null}
              </tbody>
            </table>
          </div>
        </main>
        <aside className="app-card" style={{ padding: 14, display: "grid", gap: 12, alignContent: "start" }}>
          <div className="panel-heading" style={{ padding: 0, border: 0 }}>Inspector</div>
          {selected ? (
            <>
              <div>
                <div style={{ fontSize: 18, fontWeight: 650 }}>{selected.name}</div>
                <div style={{ color: "var(--muted)", marginTop: 4 }}>{WORKSPACE_LABELS[selected.item_type]} · {selected.resource_type ?? "folder"}</div>
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {selected.href ? <Link className="btn-primary" href={selected.href}>Open</Link> : null}
                <button className="btn-ghost" onClick={renameSelected}>Rename</button>
                <button className="btn-ghost" onClick={shareEveryone}>Share everyone</button>
                <button className="btn-ghost" onClick={removeSelected}>Delete</button>
              </div>
              <div>
                <div className="panel-heading" style={{ padding: "0 0 8px", border: 0 }}>Permissions</div>
                {perms.length === 0 ? <div style={{ color: "var(--muted)" }}>No explicit grants visible.</div> : perms.map((p) => (
                  <div key={p.id} className="badge" style={{ marginRight: 4, marginBottom: 4 }}>
                    {p.subject_type}{p.subject_id ? `:${p.subject_id.slice(0, 8)}` : ""} · {p.can_manage ? "manage" : p.can_edit ? "edit" : p.can_view ? "view" : "none"}
                  </div>
                ))}
              </div>
              <div>
                <div className="panel-heading" style={{ padding: "0 0 8px", border: 0 }}>Favorites</div>
                {favorites.map((f) => <Link key={f.id} href={f.path ?? "#"} className="badge" style={{ marginRight: 4, marginBottom: 4 }}>{f.title}</Link>)}
                {!favorites.length ? <div style={{ color: "var(--muted)" }}>No favorites yet.</div> : null}
              </div>
            </>
          ) : <div style={{ color: "var(--muted)" }}>Select a file or folder.</div>}
        </aside>
      </div>
      )}
    </div>
  );
}
