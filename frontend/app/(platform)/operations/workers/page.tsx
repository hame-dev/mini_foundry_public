"use client";

import { useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { Badge, StatusPill } from "@/components/foundry";
import { operationsApi, type Workers } from "@/lib/api/endpoints/operations";
import { ApiError } from "@/lib/api";

export default function OperationsWorkersPage() {
  const [data, setData] = useState<Workers | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError(null);
    try {
      setData(await operationsApi.workers());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load workers.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(true), 30000);
    return () => window.clearInterval(timer);
  }, [load]);

  return (
    <div className="space-y-5">
      <ResourceHeader
        title="Workers"
        type="Operations"
        status={data ? (data.configured ? "Online" : "Not configured") : "Loading"}
        actions={
          <button type="button" className="toolbar-button" onClick={() => void load(true)}>
            Refresh
          </button>
        }
      />

      {loading ? <LoadingState label="Inspecting workers..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && !error && data ? (
        data.configured && data.workers.length ? (
          <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {data.workers.map((w) => (
              <article key={w.name} className="app-card p-4">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="font-semibold break-all">{w.name}</h2>
                  <StatusPill status={w.status} />
                </div>
                <dl className="mt-4 grid gap-2 text-xs text-[var(--muted)]">
                  <div className="flex items-center justify-between">
                    <dt>Active tasks</dt>
                    <dd className="text-[var(--text)]">{w.active_task_count}</dd>
                  </div>
                  {w.pool ? (
                    <div className="flex items-center justify-between">
                      <dt>Pool</dt>
                      <dd className="text-[var(--text)]">{w.pool}</dd>
                    </div>
                  ) : null}
                </dl>
              </article>
            ))}
          </section>
        ) : (
          <EmptyState
            title="No workers responding"
            detail="No Celery workers answered the inspect ping. Start a worker process to see live status here."
          />
        )
      ) : null}

      {data && !data.configured ? <Badge tone="warning">Broker reachable, no workers online</Badge> : null}
    </div>
  );
}
