"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { ErrorState, LoadingState } from "@/components/platform/States";
import { apiFetch } from "@/lib/api";
import { useActiveBranch } from "@/lib/branchContext";
import type { DashboardDetail } from "@/lib/dashboards";

export default function DashboardPublishPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [dashboard, setDashboard] = useState<DashboardDetail | null>(null);
  const { branchName, setBranchName } = useActiveBranch();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<DashboardDetail>(`/dashboards/${id}`).then(setDashboard).catch((err) => setError(err instanceof Error ? err.message : "Unable to load dashboard."));
  }, [id]);

  async function publish() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const published = await apiFetch<DashboardDetail>(`/dashboards/${id}/publish?branch_name=${encodeURIComponent(branchName || "main")}`, { method: "POST" });
      setDashboard(published);
      setMessage(`Published version ${published.published_version}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Publish failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader
        title={dashboard?.title ?? "Publish dashboard"}
        type="Dashboard"
        status={dashboard ? `v${dashboard.published_version}` : "Loading"}
        actions={<Link className="toolbar-button" href={`/apps/dashboards/${id}/preview`}>Preview</Link>}
      />
      {!dashboard && !error ? <LoadingState label="Loading dashboard..." /> : null}
      {error ? <ErrorState message={error} /> : null}
      {dashboard ? (
        <section className="app-card p-4">
          <h2 className="font-semibold">Publish snapshot</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">Publishing freezes the current dashboard layout as the stable viewer state.</p>
          <label className="mt-4 block text-xs font-medium text-[var(--muted)]">
            Branch
            <input className="input-dark mt-1 w-full max-w-xs" value={branchName} onChange={(event) => setBranchName(event.target.value)} />
          </label>
          <div className="mt-4 flex flex-wrap gap-2">
            <button className="toolbar-button" type="button" disabled={busy} onClick={() => void publish()}>{busy ? "Publishing" : "Publish"}</button>
            <Link className="toolbar-button" href={`/apps/dashboards/${id}/edit`}>Back to editor</Link>
          </div>
          {message ? <p className="mt-3 text-sm text-emerald-200">{message}</p> : null}
        </section>
      ) : null}
    </div>
  );
}
