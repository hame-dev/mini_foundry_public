"use client";

import { useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { ErrorState, LoadingState } from "@/components/platform/States";
import { StatusPill } from "@/components/foundry";
import { operationsApi, type Storage } from "@/lib/api/endpoints/operations";
import { ApiError } from "@/lib/api";

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export default function OperationsStoragePage() {
  const [data, setData] = useState<Storage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await operationsApi.storage());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load storage info.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-5">
      <ResourceHeader
        title="Storage"
        type="Operations"
        status={data ? (data.reachable ? "Reachable" : "Unreachable") : "Loading"}
        actions={
          <button type="button" className="toolbar-button" onClick={() => void load()}>
            Refresh
          </button>
        }
      />

      {loading ? <LoadingState label="Inspecting object storage..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && !error && data ? (
        <>
          <section className="grid gap-3 md:grid-cols-4">
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Backend</p>
              <p className="mt-2 text-lg font-semibold uppercase">{data.backend}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Status</p>
              <div className="mt-2">
                <StatusPill status={data.reachable ? "ok" : "error"} />
              </div>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Objects</p>
              <p className="mt-2 text-2xl font-semibold">{data.object_count ?? "—"}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Total size</p>
              <p className="mt-2 text-2xl font-semibold">{formatBytes(data.total_bytes)}</p>
            </div>
          </section>

          <section className="app-card p-4">
            <dl className="grid gap-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-[var(--muted)]">Location</dt>
                <dd className="font-mono text-xs">{data.location}</dd>
              </div>
              {data.detail ? (
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-[var(--muted)]">Detail</dt>
                  <dd className="max-w-[70%] truncate text-right text-red-300">{data.detail}</dd>
                </div>
              ) : null}
            </dl>
          </section>
        </>
      ) : null}
    </div>
  );
}
