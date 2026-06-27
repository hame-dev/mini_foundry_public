"use client";

import { useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { Badge } from "@/components/foundry";
import { operationsApi, type Queues } from "@/lib/api/endpoints/operations";
import { ApiError } from "@/lib/api";

export default function OperationsQueuesPage() {
  const [data, setData] = useState<Queues | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError(null);
    try {
      setData(await operationsApi.queues());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load queues.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(true), 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  return (
    <div className="space-y-5">
      <ResourceHeader
        title="Queues"
        type="Operations"
        status={data ? "Live" : "Loading"}
        actions={
          <button type="button" className="toolbar-button" onClick={() => void load(true)}>
            Refresh
          </button>
        }
      />

      {loading ? <LoadingState label="Reading queue depths..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && !error && data ? (
        data.queues.length ? (
          <section className="app-card overflow-hidden">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-[var(--muted)]">
                <tr>
                  <th className="px-4 py-3">Queue</th>
                  <th className="px-4 py-3">Depth</th>
                </tr>
              </thead>
              <tbody>
                {data.queues.map((q) => (
                  <tr key={q.name} className="border-t border-[var(--border)]">
                    <td className="px-4 py-3 font-medium">{q.name}</td>
                    <td className="px-4 py-3">
                      <Badge tone={q.depth > 0 ? "warning" : "neutral"}>{q.depth}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : (
          <EmptyState title="No queues" detail="No task queues are configured." />
        )
      ) : null}

      <p className="text-xs text-[var(--muted)]">Refreshes every 15 seconds.</p>
    </div>
  );
}
