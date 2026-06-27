"use client";

import { useEffect, useState } from "react";
import { decideApproval, listApprovals, type ApprovalRequest } from "@/lib/governance";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { StatusPill } from "@/components/platform/StatusPill";

export default function ApprovalsPage() {
  const [rows, setRows] = useState<ApprovalRequest[]>([]);
  const [status, setStatus] = useState("pending");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(nextStatus = status) {
    setLoading(true);
    try {
      setRows(await listApprovals(nextStatus));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load approvals");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(status); }, [status]); // eslint-disable-line react-hooks/exhaustive-deps

  async function decide(row: ApprovalRequest, approve: boolean) {
    setBusyId(row.id);
    try {
      await decideApproval(row.id, approve, approve ? "Approved from approval queue" : "Rejected from approval queue");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Decision failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <ResourceHeader title="Approval queue" type="Governance queue" status={status} />
      <div className="app-card p-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-[var(--muted)]">Status</span>
        {["pending", "approved", "rejected"].map((item) => (
          <button key={item} className={status === item ? "btn-primary text-xs" : "btn-ghost text-xs"} onClick={() => setStatus(item)}>
            {item}
          </button>
        ))}
      </div>
      {error ? <ErrorState message={error} /> : null}
      {loading ? <LoadingState label="Loading approvals..." /> : rows.length === 0 ? (
        <EmptyState title="No approvals" detail="Export and action approval requests appear here for authorized reviewers." />
      ) : (
        <div className="app-card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left border-b border-[var(--line)] text-[var(--muted)]">
                <th className="p-3">Type</th>
                <th className="p-3">Resource</th>
                <th className="p-3">Requester</th>
                <th className="p-3">Details</th>
                <th className="p-3">Status</th>
                <th className="p-3 text-right">Decision</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-[var(--line-soft)] align-top">
                  <td className="p-3"><span className="topbar-pill">{row.approval_type}</span></td>
                  <td className="p-3 font-mono text-xs">{row.resource_id || "not linked"}</td>
                  <td className="p-3 font-mono text-xs">{row.requester_id || "unknown"}</td>
                  <td className="p-3">
                    <pre className="max-h-24 overflow-auto rounded p-2 text-xs" style={{ background: "var(--panel-2)" }}>
                      {JSON.stringify(row.details, null, 2)}
                    </pre>
                  </td>
                  <td className="p-3"><StatusPill status={row.status} /></td>
                  <td className="p-3">
                    <div className="flex justify-end gap-2">
                      <button className="btn-ghost text-xs" disabled={row.status !== "pending" || busyId === row.id} onClick={() => void decide(row, false)}>Reject</button>
                      <button className="btn-primary text-xs" disabled={row.status !== "pending" || busyId === row.id} onClick={() => void decide(row, true)}>Approve</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
