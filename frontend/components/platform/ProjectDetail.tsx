"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { ApiError } from "@/lib/api";
import {
  abandonProjectBranch, compareBranch, createProjectBranch, getProject, grantProjectAccess, listProjectAccess, listProjectActivity, listProjectBranches,
  mergeProjectBranch, requestBranchReview,
  listProjectResources, revokeProjectAccess, PROJECT_CAPABILITIES,
  type BranchCompare, type ProjectAccess, type ProjectActivityEvent, type ProjectBranch, type ProjectDetail as TProjectDetail,
  type PlatformResource,
} from "@/lib/projects";

type Tab = "overview" | "access" | "activity" | "branches";
const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "access", label: "Access" },
  { id: "activity", label: "Activity" },
  { id: "branches", label: "Branches" },
];

export function ProjectDetail({ projectId, initialTab = "overview" }: { projectId: string; initialTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [project, setProject] = useState<TProjectDetail | null>(null);
  const [resources, setResources] = useState<PlatformResource[]>([]);
  const [access, setAccess] = useState<ProjectAccess[]>([]);
  const [activity, setActivity] = useState<ProjectActivityEvent[]>([]);
  const [branches, setBranches] = useState<ProjectBranch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [subjectType, setSubjectType] = useState("role");
  const [subjectId, setSubjectId] = useState("");
  const [caps, setCaps] = useState<string[]>(["view_metadata"]);
  const [branchName, setBranchName] = useState("");
  const [selectedCompare, setSelectedCompare] = useState<BranchCompare | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, r, a, ev, b] = await Promise.all([
        getProject(projectId),
        listProjectResources(projectId).catch(() => []),
        listProjectAccess(projectId).catch(() => []),
        listProjectActivity(projectId).then((x) => x.events).catch(() => []),
        listProjectBranches(projectId).catch(() => []),
      ]);
      setProject(p);
      setResources(r);
      setAccess(a);
      setActivity(ev);
      setBranches(b);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load project.");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function grant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await grantProjectAccess(projectId, {
        subject_type: subjectType,
        subject_id: subjectType === "all_users" ? null : subjectId.trim() || null,
        capabilities: caps,
      });
      setSubjectId("");
      setAccess(await listProjectAccess(projectId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to grant access.");
    }
  }

  async function revoke(aclId: string) {
    try {
      await revokeProjectAccess(projectId, aclId);
      setAccess(await listProjectAccess(projectId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to revoke access.");
    }
  }

  async function createBranch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = branchName.trim();
    if (!name) return;
    try {
      await createProjectBranch({ name, project_id: projectId });
      setBranchName("");
      setBranches(await listProjectBranches(projectId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create branch.");
    }
  }

  async function refreshBranch(branchId?: string) {
    const next = await listProjectBranches(projectId);
    setBranches(next);
    if (branchId) {
      try {
        setSelectedCompare(await compareBranch(branchId));
      } catch {
        setSelectedCompare(null);
      }
    }
  }

  async function openCompare(branchId: string) {
    try {
      setSelectedCompare(await compareBranch(branchId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to compare branch.");
    }
  }

  async function sendReview(branchId: string) {
    try {
      await requestBranchReview(branchId);
      await refreshBranch(branchId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to request review.");
    }
  }

  async function mergeBranch(branchId: string) {
    try {
      await mergeProjectBranch(branchId);
      await refreshBranch(branchId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to merge branch.");
    }
  }

  async function abandonBranch(branchId: string) {
    try {
      await abandonProjectBranch(branchId);
      await refreshBranch();
      if (selectedCompare?.branch.id === branchId) setSelectedCompare(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to abandon branch.");
    }
  }

  if (loading) return <LoadingState label="Loading project..." />;
  if (error && !project) return <ErrorState message={error} />;

  return (
    <div className="space-y-5">
      <ResourceHeader
        title={project?.name ?? "Project"}
        type="Workspace · Project"
        subtitle={project?.description ?? undefined}
        status={`${project?.resource_total ?? 0} resources`}
      />
      {error ? <ErrorState message={error} /> : null}

      <nav className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button key={t.id} type="button" className={`toolbar-button ${tab === t.id ? "bg-[var(--panel-2)]" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "overview" ? (
        <section className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            {Object.entries(project?.resource_counts ?? {}).map(([type, count]) => (
              <div key={type} className="app-card p-4">
                <p className="text-xs uppercase tracking-wide text-[var(--muted)]">{type}</p>
                <p className="mt-2 text-2xl font-semibold">{count}</p>
              </div>
            ))}
            {!Object.keys(project?.resource_counts ?? {}).length ? <EmptyState title="No resources in this project yet" /> : null}
          </div>
          {resources.length ? (
            <section className="app-card overflow-hidden">
              <table className="w-full text-left text-sm">
                <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                  <tr><th className="px-4 py-3">Name</th><th className="px-4 py-3">Type</th></tr>
                </thead>
                <tbody>
                  {resources.filter((r) => r.resource_type !== "project").map((r) => (
                    <tr key={r.id} className="border-t border-[var(--line-soft)]">
                      <td className="px-4 py-3">{r.name}</td>
                      <td className="px-4 py-3 text-[var(--muted)]">{r.resource_type}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}
        </section>
      ) : null}

      {tab === "access" ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <section className="app-card overflow-hidden">
            {access.length ? (
              <table className="w-full text-left text-sm">
                <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                  <tr><th className="px-4 py-3">Subject</th><th className="px-4 py-3">Capabilities</th><th className="px-4 py-3" /></tr>
                </thead>
                <tbody>
                  {access.map((a) => (
                    <tr key={a.id} className="border-t border-[var(--line-soft)]">
                      <td className="px-4 py-3 text-xs">{a.subject_type}{a.subject_id ? ` · ${a.subject_id.slice(0, 8)}` : ""}</td>
                      <td className="px-4 py-3 font-mono text-xs">{a.capabilities.join(", ")}</td>
                      <td className="px-4 py-3 text-right"><button type="button" className="toolbar-button" onClick={() => void revoke(a.id)}>Revoke</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-4"><EmptyState title="No access grants" detail="Owner and inherited grants apply implicitly." /></div>
            )}
          </section>
          <aside>
            <form className="app-card space-y-3 p-4" onSubmit={grant}>
              <h2 className="font-semibold">Grant access</h2>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Subject type
                <select className="input-dark mt-1 w-full" value={subjectType} onChange={(e) => setSubjectType(e.target.value)}>
                  <option value="user">user</option>
                  <option value="role">role</option>
                  <option value="group">group</option>
                  <option value="all_users">all_users</option>
                </select>
              </label>
              {subjectType !== "all_users" ? (
                <label className="block text-xs font-medium text-[var(--muted)]">
                  Subject ID
                  <input className="input-dark mt-1 w-full" value={subjectId} onChange={(e) => setSubjectId(e.target.value)} placeholder="user/role/group UUID" />
                </label>
              ) : null}
              <fieldset className="text-xs text-[var(--muted)]">
                Capabilities
                <div className="mt-1 grid max-h-40 grid-cols-2 gap-1 overflow-y-auto">
                  {PROJECT_CAPABILITIES.map((c) => (
                    <label key={c} className="flex items-center gap-1 text-[var(--text)]">
                      <input type="checkbox" checked={caps.includes(c)} onChange={() => setCaps((cur) => cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c])} />
                      {c}
                    </label>
                  ))}
                </div>
              </fieldset>
              <button type="submit" className="toolbar-button w-full justify-center" disabled={!caps.length || (subjectType !== "all_users" && !subjectId.trim())}>
                Grant
              </button>
            </form>
          </aside>
        </div>
      ) : null}

      {tab === "activity" ? (
        <section className="app-card overflow-hidden">
          {activity.length ? (
            <table className="w-full text-left text-sm">
              <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                <tr><th className="px-4 py-3">When</th><th className="px-4 py-3">Event</th><th className="px-4 py-3">Resource</th></tr>
              </thead>
              <tbody>
                {activity.map((e) => (
                  <tr key={e.id} className="border-t border-[var(--line-soft)]">
                    <td className="px-4 py-2 whitespace-nowrap text-xs text-[var(--muted)]">{new Date(e.created_at).toLocaleString()}</td>
                    <td className="px-4 py-2 font-mono text-xs">{e.event_type}</td>
                    <td className="px-4 py-2 text-xs">{e.resource_type || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-4"><EmptyState title="No activity" detail="Events for this project's resources will appear here." /></div>
          )}
        </section>
      ) : null}

      {tab === "branches" ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <section className="app-card overflow-hidden">
            {branches.length ? (
              <table className="w-full text-left text-sm">
                <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                  <tr><th className="px-4 py-3">Branch</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Created</th><th className="px-4 py-3" /></tr>
                </thead>
                <tbody>
                  {branches.map((b) => (
                    <tr key={b.id} className="border-t border-[var(--line-soft)]">
                      <td className="px-4 py-2 font-medium">{b.name}</td>
                      <td className="px-4 py-2 text-xs"><span className="badge">{b.status}</span></td>
                      <td className="px-4 py-2 text-xs text-[var(--muted)]">{new Date(b.created_at).toLocaleDateString()}</td>
                      <td className="px-4 py-2">
                        <div className="flex flex-wrap justify-end gap-2">
                          <button type="button" className="toolbar-button" onClick={() => void openCompare(b.id)}>Compare</button>
                          {b.status === "active" ? <button type="button" className="toolbar-button" onClick={() => void sendReview(b.id)}>Review</button> : null}
                          {b.status === "active" || b.status === "review" ? <button type="button" className="toolbar-button" onClick={() => void mergeBranch(b.id)}>Merge</button> : null}
                          {b.status !== "merged" && b.status !== "abandoned" ? <button type="button" className="toolbar-button" onClick={() => void abandonBranch(b.id)}>Abandon</button> : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-4"><EmptyState title="No branches" detail="Branches scoped to this project will appear here." /></div>
            )}
          </section>
          <aside className="space-y-4">
            <form className="app-card space-y-3 p-4" onSubmit={createBranch}>
              <h2 className="font-semibold">Create branch</h2>
              <input className="input-dark w-full" value={branchName} onChange={(event) => setBranchName(event.target.value)} placeholder="feature-review" />
              <button type="submit" className="toolbar-button w-full justify-center" disabled={!branchName.trim()}>Create</button>
            </form>
            <BranchComparePanel comparison={selectedCompare} />
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function BranchComparePanel({ comparison }: { comparison: BranchCompare | null }) {
  if (!comparison) return <div className="app-card p-4"><EmptyState title="No branch selected" detail="Compare a branch to review changed resources and conflicts." /></div>;
  return (
    <section className="app-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{comparison.branch.name}</h2>
          <p className="text-xs text-[var(--muted)]">{comparison.changes.length} changed resources</p>
        </div>
        <span className={comparison.mergeable ? "badge badge-success" : "badge badge-danger"}>{comparison.mergeable ? "mergeable" : "conflicts"}</span>
      </div>
      {comparison.conflicts.length ? (
        <div className="mt-3 rounded border border-[var(--danger)] p-3 text-xs text-[var(--danger)]">
          Parent branch moved for {comparison.conflicts.length} resource{comparison.conflicts.length === 1 ? "" : "s"}. Rebase or resolve before merging.
        </div>
      ) : null}
      <div className="mt-4 grid gap-2">
        {comparison.changes.length ? comparison.changes.map((change) => (
          <div key={change.branch_version_id} className="rounded border border-[var(--line-soft)] p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{change.name || change.resource_id}</span>
              <span className="badge">{change.resource_type || "resource"}</span>
            </div>
            <p className="mt-1 font-mono text-xs text-[var(--muted)]">branch v{change.branch_version_number}</p>
            {change.main_changed_after_branch ? <p className="mt-2 text-xs text-[var(--danger)]">Main changed after branch creation.</p> : null}
          </div>
        )) : <EmptyState title="No changes" detail="This branch has no resource versions to merge." />}
      </div>
    </section>
  );
}
