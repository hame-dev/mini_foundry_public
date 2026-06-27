"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { createExportRequest, listExports, type ExportRequest } from "@/lib/governance";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { StatusPill } from "@/components/platform/StatusPill";

export default function ExportControlsPage() {
  const [rows, setRows] = useState<ExportRequest[]>([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resourceId, setResourceId] = useState("");
  const [purpose, setPurpose] = useState("");
  const [destination, setDestination] = useState("");

  const loadExports = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await listExports(status || undefined));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load exports");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void loadExports();
  }, [loadExports]);

  async function requestExport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!resourceId.trim() || !purpose.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createExportRequest({
        resource_id: resourceId.trim(),
        purpose: purpose.trim(),
        destination: destination.trim() || null,
        details: {},
      });
      setResourceId("");
      setPurpose("");
      setDestination("");
      await loadExports();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to request export");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <ResourceHeader title="Export controls" type="Governance" status={status || "all"} />
      <form className="app-card grid gap-3 p-4 xl:grid-cols-[minmax(0,1fr)_minmax(240px,0.7fr)_minmax(220px,0.7fr)_auto]" onSubmit={requestExport}>
        <label className="block text-xs font-medium text-[var(--muted)]">
          Resource ID
          <input className="input-dark mt-1 w-full" value={resourceId} onChange={(event) => setResourceId(event.target.value)} />
        </label>
        <label className="block text-xs font-medium text-[var(--muted)]">
          Purpose
          <input className="input-dark mt-1 w-full" value={purpose} onChange={(event) => setPurpose(event.target.value)} />
        </label>
        <label className="block text-xs font-medium text-[var(--muted)]">
          Destination
          <input className="input-dark mt-1 w-full" value={destination} onChange={(event) => setDestination(event.target.value)} />
        </label>
        <div className="flex items-end">
          <button type="submit" className="toolbar-button w-full justify-center" disabled={saving || !resourceId.trim() || !purpose.trim()}>
            {saving ? "Requesting" : "Request export"}
          </button>
        </div>
      </form>
      <div className="app-card p-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-[var(--muted)]">Status</span>
        {["", "pending_approval", "approved", "rejected"].map((item) => (
          <button key={item || "all"} className={status === item ? "btn-primary text-xs" : "btn-ghost text-xs"} onClick={() => setStatus(item)}>
            {item || "all"}
          </button>
        ))}
      </div>
      {error ? <ErrorState message={error} /> : null}
      {loading ? <LoadingState label="Loading export requests..." /> : rows.length === 0 ? (
        <EmptyState title="No export requests" detail="Governed export requests and their approval status appear here." />
      ) : (
        <div className="app-card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left border-b border-[var(--line)] text-[var(--muted)]">
                <th className="p-3">Purpose</th>
                <th className="p-3">Resource</th>
                <th className="p-3">Requester</th>
                <th className="p-3">Destination</th>
                <th className="p-3">Approval</th>
                <th className="p-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-b border-[var(--line-soft)]">
                  <td className="p-3">{row.purpose}</td>
                  <td className="p-3 font-mono text-xs">{row.resource_id || "not linked"}</td>
                  <td className="p-3 font-mono text-xs">{row.requester_id || "unknown"}</td>
                  <td className="p-3">{row.destination || "not specified"}</td>
                  <td className="p-3 font-mono text-xs">{row.approval_request_id || "none"}</td>
                  <td className="p-3"><StatusPill status={row.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
