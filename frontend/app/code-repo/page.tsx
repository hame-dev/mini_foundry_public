"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { CodeRepositorySummary, ResourceActivity } from "@/lib/types";
import { ModuleCard, ResourceHeader } from "@/components/foundry/FoundryPrimitives";

export default function CodeRepoLandingPage() {
  const [repos, setRepos] = useState<CodeRepositorySummary[]>([]);
  const [recents, setRecents] = useState<ResourceActivity[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const [repoRows, recentRows] = await Promise.all([
      apiFetch<CodeRepositorySummary[]>("/code-repo/repositories"),
      apiFetch<ResourceActivity[]>("/activity/recents?limit=8").catch(() => []),
    ]);
    setRepos(repoRows);
    setRecents(recentRows.filter((r) => r.resource_type === "code_repository" || r.resource_type === "notebook"));
  }

  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, []);

  async function createRepo(repo_type = "python_transforms") {
    const name = prompt("Repository name", repo_type === "functions" ? "Functions repository" : "Python transforms");
    if (!name) return;
    const repo = await apiFetch<CodeRepositorySummary>("/code-repo/repositories", {
      method: "POST",
      body: JSON.stringify({ name, repo_type, description: "Created from Code Repositories" }),
    });
    window.location.href = `/code-repo/${repo.id}`;
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <ResourceHeader
        eyebrow="Code Repositories"
        title="Production Code And Code Workspaces"
        subtitle="Author transforms, functions, notebooks, and reviewable changes from one resource home."
        tabs={[
          { label: "Code", id: "Code" },
          { label: "Branches", id: "Branches" },
          { label: "Pull Requests", id: "Pull Requests" },
          { label: "Code Workspaces", href: "/notebooks" },
        ]}
        activeTab="Code"
        actions={
          <>
            <button className="btn-ghost" onClick={() => createRepo("functions")}>New functions repo</button>
            <button className="btn-primary" onClick={() => createRepo("python_transforms")}>New repository</button>
          </>
        }
      />
      {error ? <div className="app-card" style={{ padding: 12, color: "var(--danger)" }}>Load failed: {error}</div> : null}

      <div className="foundry-grid">
        <button onClick={() => createRepo("python_transforms")} style={{ textAlign: "left", border: 0, background: "transparent", padding: 0 }}>
          <ModuleCard title="Python transforms repo" subtitle="Git-backed transforms with tests, branches, commits, and pull requests." icon="{}" />
        </button>
        <button onClick={() => createRepo("functions")} style={{ textAlign: "left", border: 0, background: "transparent", padding: 0 }}>
          <ModuleCard title="Functions repo" subtitle="Business logic and ontology functions for operational apps." icon="fx" />
        </button>
        <Link href="/notebooks/new" style={{ textDecoration: "none", color: "inherit" }}>
          <ModuleCard title="Code Workspace / Notebook" subtitle="Jupyter-style exploratory Python or SQL workspace using the existing sandbox." icon="[]" />
        </Link>
      </div>

      <div className="foundry-workbench">
        <section className="app-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="section-header">
            <div className="section-header-title">Repositories</div>
            <span className="badge">{repos.length}</span>
          </div>
          <table>
            <thead><tr><th>Name</th><th>Type</th><th>Branch</th><th>Updated</th></tr></thead>
            <tbody>
              {repos.map((repo) => (
                <tr key={repo.id}>
                  <td><Link className="text-blue-600" href={`/code-repo/${repo.id}`}>{repo.name}</Link><div style={{ color: "var(--muted)", fontSize: 12 }}>{repo.description}</div></td>
                  <td><span className="badge">{repo.repo_type.replace(/_/g, " ")}</span></td>
                  <td>{repo.default_branch}</td>
                  <td>{new Date(repo.updated_at).toLocaleString()}</td>
                </tr>
              ))}
              {!repos.length ? <tr><td colSpan={4}><div className="empty-state"><div className="empty-state-title">No repositories yet</div></div></td></tr> : null}
            </tbody>
          </table>
        </section>
        <aside className="app-card" style={{ padding: 0 }}>
          <div className="panel-heading">Recent Workspaces</div>
          <div style={{ padding: 12, display: "grid", gap: 8 }}>
            {recents.map((item) => (
              <Link key={item.id} className="btn-ghost" href={item.path ?? "#"}>{item.title}</Link>
            ))}
            {!recents.length ? <div style={{ color: "var(--muted)" }}>Open a repo or notebook to populate this list.</div> : null}
          </div>
        </aside>
      </div>
    </div>
  );
}
