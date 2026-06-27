"use client";
import Link from "next/link";
import { use, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Branch = {
  id: string;
  dataset_id: string;
  branch_name: string;
  parent_branch: string;
  status: string;
  merged_into: string | null;
  created_at: string;
};

type DiffResult = {
  status: string;
  columns?: string[];
  added?: Record<string, unknown>[];
  removed?: Record<string, unknown>[];
  added_count?: number;
  removed_count?: number;
  message?: string;
};

const STATUS_BADGE: Record<string, string> = {
  open: "badge badge-success",
  committed: "badge badge-accent",
  merged: "badge",
  aborted: "badge",
};

export default function BranchesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [fromBranch, setFromBranch] = useState("main");
  const [creating, setCreating] = useState(false);

  const [diff, setDiff] = useState<{ txnId: string; result: DiffResult } | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

  const [mergeTarget, setMergeTarget] = useState("main");

  const loadBranches = () => {
    setLoading(true);
    apiFetch<Branch[]>(`/catalog/datasets/${id}/branches`)
      .then(setBranches)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(loadBranches, [id]);

  const createBranch = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await apiFetch(`/catalog/datasets/${id}/branches`, {
        method: "POST",
        body: JSON.stringify({ branch_name: newName.trim(), from_branch: fromBranch }),
      });
      setNewName("");
      setFromBranch("main");
      setShowCreate(false);
      loadBranches();
    } catch (e: any) {
      alert(e.message);
    } finally {
      setCreating(false);
    }
  };

  const commitBranch = async (txnId: string) => {
    try {
      await apiFetch(`/catalog/datasets/${id}/branches/${txnId}/commit`, { method: "POST" });
      loadBranches();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const mergeBranch = async (txnId: string) => {
    try {
      const report = await apiFetch<any>(`/catalog/datasets/${id}/branches/${txnId}/merge`, {
        method: "POST",
        body: JSON.stringify({ target_branch: mergeTarget }),
      });
      alert(
        report.status === "conflict"
          ? `Merge conflict detected!\nMissing in target: ${report.missing_in_target?.join(", ")}`
          : `Merged successfully. ${report.rows_merged ?? ""} rows applied.`
      );
      loadBranches();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const abortBranch = async (txnId: string) => {
    if (!confirm("Abort this branch? The isolated data will be deleted.")) return;
    try {
      await apiFetch(`/catalog/datasets/${id}/branches/${txnId}`, { method: "DELETE" });
      loadBranches();
    } catch (e: any) {
      alert(e.message);
    }
  };

  const viewDiff = async (txnId: string) => {
    setDiffLoading(true);
    setDiff(null);
    try {
      const result = await apiFetch<DiffResult>(`/catalog/datasets/${id}/branches/${txnId}/diff`);
      setDiff({ txnId, result });
    } catch (e: any) {
      alert(e.message);
    } finally {
      setDiffLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <header className="page-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="page-header-eyebrow">
            <Link href={`/catalog/${id}`} className="hover:underline text-blue-600">Dataset</Link>
            {" / "}Branches
          </div>
          <h1 className="page-header-title">Data Branches</h1>
          <p style={{ color: "var(--muted)", fontSize: 13, marginTop: 4 }}>
            Each branch is a physical copy of the dataset isolated for safe experimentation.
          </p>
        </div>
        <button onClick={() => setShowCreate(!showCreate)} className="btn-primary text-sm">
          + New Branch
        </button>
      </header>

      {showCreate && (
        <div className="app-card p-5 space-y-4">
          <h3 className="font-semibold text-sm">Create Branch</h3>
          <div className="flex gap-3 items-end flex-wrap">
            <div>
              <label className="block text-xs mb-1" style={{ color: "var(--muted)" }}>Branch name</label>
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="feature-experiment"
                className="input-dark"
                style={{ width: 200 }}
              />
            </div>
            <div>
              <label className="block text-xs mb-1" style={{ color: "var(--muted)" }}>From branch</label>
              <select
                value={fromBranch}
                onChange={(e) => setFromBranch(e.target.value)}
                className="input-dark"
                style={{ width: 140 }}
              >
                <option value="main">main</option>
                {branches
                  .filter((b) => b.status !== "aborted" && b.branch_name !== "main")
                  .map((b) => (
                    <option key={b.id} value={b.branch_name}>
                      {b.branch_name}
                    </option>
                  ))}
              </select>
            </div>
            <button
              onClick={createBranch}
              disabled={creating || !newName.trim()}
              className="btn-primary text-sm disabled:opacity-50"
            >
              {creating ? "Creating…" : "Create"}
            </button>
            <button onClick={() => setShowCreate(false)} className="btn-ghost text-sm">
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="app-card p-4 text-red-600 text-sm">{error}</div>
      )}

      {loading ? (
        <div className="app-card empty-state">
          <div className="empty-state-title">Loading branches…</div>
        </div>
      ) : branches.length === 0 ? (
        <div className="app-card empty-state">
          <div className="empty-state-title">No branches yet</div>
          <div className="empty-state-help">Create a branch to experiment with your data safely.</div>
        </div>
      ) : (
        <div className="app-card overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>Branch</th>
                <th>From</th>
                <th>Status</th>
                <th>Merged Into</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {branches.map((b) => (
                <tr key={b.id}>
                  <td className="font-mono font-semibold">{b.branch_name}</td>
                  <td className="font-mono" style={{ color: "var(--muted)" }}>{b.parent_branch}</td>
                  <td>
                    <span className={STATUS_BADGE[b.status] ?? "badge"}>{b.status}</span>
                  </td>
                  <td className="font-mono" style={{ color: "var(--muted)" }}>{b.merged_into ?? "—"}</td>
                  <td style={{ color: "var(--muted)" }}>{new Date(b.created_at).toLocaleDateString()}</td>
                  <td>
                    {b.status === "open" || b.status === "committed" ? (
                      <div className="flex gap-2 items-center flex-wrap">
                        <button onClick={() => viewDiff(b.id)} className="btn-ghost" style={{ fontSize: 11 }}>
                          Diff
                        </button>
                        {b.status === "open" && (
                          <button onClick={() => commitBranch(b.id)} className="btn-ghost" style={{ fontSize: 11, color: "var(--accent)" }}>
                            Commit
                          </button>
                        )}
                        <div className="flex gap-1 items-center">
                          <select
                            value={mergeTarget}
                            onChange={(e) => setMergeTarget(e.target.value)}
                            className="input-dark"
                            style={{ fontSize: 11, padding: "2px 6px", width: "auto" }}
                          >
                            <option value="main">main</option>
                            {branches
                              .filter((x) => x.branch_name !== b.branch_name && x.status !== "aborted")
                              .map((x) => (
                                <option key={x.id} value={x.branch_name}>{x.branch_name}</option>
                              ))}
                          </select>
                          <button onClick={() => mergeBranch(b.id)} className="btn-primary" style={{ fontSize: 11 }}>
                            Merge →
                          </button>
                        </div>
                        <button onClick={() => abortBranch(b.id)} className="btn-ghost" style={{ fontSize: 11, color: "var(--danger)" }}>
                          Abort
                        </button>
                      </div>
                    ) : (
                      <span style={{ color: "var(--muted-2)", fontSize: 12 }}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Diff Viewer */}
      {(diffLoading || diff) && (
        <div className="app-card p-5 space-y-4">
          <h3 className="font-semibold text-sm">Branch Diff</h3>
          {diffLoading && <p className="text-sm" style={{ color: "var(--muted)" }}>Loading diff…</p>}
          {diff && diff.result.status === "unsupported" && (
            <p className="text-sm" style={{ color: "var(--muted)" }}>{diff.result.message}</p>
          )}
          {diff && diff.result.status === "ok" && (
            <div className="space-y-4">
              <div className="flex gap-6 text-sm">
                <span style={{ color: "var(--success)" }} className="font-semibold">+{diff.result.added_count} added</span>
                <span style={{ color: "var(--danger)" }} className="font-semibold">−{diff.result.removed_count} removed</span>
              </div>
              {(diff.result.added?.length ?? 0) > 0 && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--success)", marginBottom: 4 }}>Added rows</div>
                  <DiffTable columns={diff.result.columns!} rows={diff.result.added!} color="green" />
                </div>
              )}
              {(diff.result.removed?.length ?? 0) > 0 && (
                <div>
                  <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--danger)", marginBottom: 4 }}>Removed rows</div>
                  <DiffTable columns={diff.result.columns!} rows={diff.result.removed!} color="red" />
                </div>
              )}
              {diff.result.added_count === 0 && diff.result.removed_count === 0 && (
                <p className="text-sm" style={{ color: "var(--muted)" }}>No differences found — branch is identical to parent.</p>
              )}
            </div>
          )}
          {diff && diff.result.status === "conflict" && (
            <p className="text-sm" style={{ color: "var(--danger)" }}>Schema conflict: {JSON.stringify(diff.result)}</p>
          )}
        </div>
      )}
    </div>
  );
}

function DiffTable({
  columns,
  rows,
  color,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  color: "green" | "red";
}) {
  const rowClass = color === "green" ? "diff-add" : "diff-remove";
  return (
    <div className="app-card overflow-auto" style={{ maxHeight: 300 }}>
      <table className="data-table" style={{ fontSize: 11 }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} className="font-mono">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={rowClass}>
              {columns.map((c) => (
                <td key={c} className="font-mono">{String(r[c] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
