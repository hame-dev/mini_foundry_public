"use client";

import { useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import {
  abandonProjectBranch,
  compareBranch,
  listBranches,
  mergeProjectBranch,
  requestBranchReview,
  type BranchCompare,
  type ProjectBranch,
} from "@/lib/projects";
import { writeActiveBranch } from "@/lib/branchContext";

export default function WorkspaceBranchesPage() {
  const [branches, setBranches] = useState<ProjectBranch[]>([]);
  const [comparison, setComparison] = useState<BranchCompare | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      setBranches(await listBranches());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load branches.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function action(branchId: string, fn: (id: string) => Promise<unknown>) {
    try {
      await fn(branchId);
      await load();
      if (comparison?.branch.id === branchId) {
        setComparison(await compareBranch(branchId).catch(() => null));
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Branch action failed.");
    }
  }

  async function openCompare(branch: ProjectBranch) {
    try {
      setComparison(await compareBranch(branch.id));
      writeActiveBranch(branch.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to compare branch.");
    }
  }

  if (loading) return <LoadingState label="Loading branches..." />;

  return (
    <div className="space-y-5">
      <ResourceHeader
        title="Branch Review"
        type="Workspace"
        subtitle="Compare branch drafts, surface parent movement conflicts, and merge approved resource versions."
        status={`${branches.length} branches`}
      />
      {error ? <ErrorState message={error} /> : null}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <section className="app-card overflow-hidden">
          {branches.length ? (
            <table className="w-full text-left text-sm">
              <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                <tr><th className="px-4 py-3">Branch</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Project</th><th className="px-4 py-3">Created</th><th className="px-4 py-3" /></tr>
              </thead>
              <tbody>
                {branches.map((branch) => (
                  <tr key={branch.id} className="border-t border-[var(--line-soft)]">
                    <td className="px-4 py-3 font-medium">{branch.name}</td>
                    <td className="px-4 py-3"><span className="badge">{branch.status}</span></td>
                    <td className="px-4 py-3 font-mono text-xs text-[var(--muted)]">{branch.project_id?.slice(0, 8) || "global"}</td>
                    <td className="px-4 py-3 text-xs text-[var(--muted)]">{new Date(branch.created_at).toLocaleString()}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap justify-end gap-2">
                        <button type="button" className="toolbar-button" onClick={() => void openCompare(branch)}>Compare</button>
                        {branch.status === "active" ? <button type="button" className="toolbar-button" onClick={() => void action(branch.id, (id) => requestBranchReview(id))}>Review</button> : null}
                        {branch.status === "active" || branch.status === "review" ? <button type="button" className="toolbar-button" onClick={() => void action(branch.id, mergeProjectBranch)}>Merge</button> : null}
                        {branch.status !== "merged" && branch.status !== "abandoned" ? <button type="button" className="toolbar-button" onClick={() => void action(branch.id, abandonProjectBranch)}>Abandon</button> : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-4"><EmptyState title="No branches" detail="Project and resource branch drafts appear here when created." /></div>
          )}
        </section>
        <aside className="app-card p-4">
          {comparison ? (
            <div>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold">{comparison.branch.name}</h2>
                  <p className="text-xs text-[var(--muted)]">{comparison.changes.length} changed resources</p>
                </div>
                <span className={comparison.mergeable ? "badge badge-success" : "badge badge-danger"}>{comparison.mergeable ? "mergeable" : "conflicts"}</span>
              </div>
              {comparison.conflicts.length ? (
                <div className="mt-3 rounded border border-[var(--danger)] p-3 text-xs text-[var(--danger)]">
                  Parent branch moved after this branch was created. Resolve the listed resources before merging.
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
                )) : <EmptyState title="No changes" detail="No branch resource versions were found." />}
              </div>
            </div>
          ) : (
            <EmptyState title="No branch selected" detail="Select Compare to inspect changed resources and merge readiness." />
          )}
        </aside>
      </div>
    </div>
  );
}
