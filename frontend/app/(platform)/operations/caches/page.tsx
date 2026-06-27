"use client";

import { useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { Button, ConfirmDialog } from "@/components/foundry";
import { operationsApi, type Caches } from "@/lib/api/endpoints/operations";
import { ApiError } from "@/lib/api";

export default function OperationsCachesPage() {
  const [data, setData] = useState<Caches | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [flushTarget, setFlushTarget] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await operationsApi.caches());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load cache info.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function confirmFlush() {
    if (!flushTarget) return;
    const prefix = flushTarget;
    setFlushTarget(null);
    try {
      const res = await operationsApi.flushCache(prefix);
      setNotice(`Flushed ${res.deleted} keys from ${prefix}`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Flush failed.");
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader
        title="Caches"
        type="Operations"
        status={data ? "Live" : "Loading"}
        actions={
          <button type="button" className="toolbar-button" onClick={() => void load()}>
            Refresh
          </button>
        }
      />

      {loading ? <LoadingState label="Inspecting Redis caches..." /> : null}
      {error ? <ErrorState message={error} /> : null}
      {notice ? <div className="app-card p-3 text-sm text-emerald-300">{notice}</div> : null}

      {!loading && !error && data ? (
        <>
          <section className="grid gap-3 md:grid-cols-3">
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Memory used</p>
              <p className="mt-2 text-2xl font-semibold">{data.used_memory_human ?? "—"}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Total keys</p>
              <p className="mt-2 text-2xl font-semibold">{data.total_keys ?? "—"}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Namespaces</p>
              <p className="mt-2 text-2xl font-semibold">{data.namespaces.length}</p>
            </div>
          </section>

          {data.namespaces.length ? (
            <section className="app-card overflow-hidden">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-[var(--muted)]">
                  <tr>
                    <th className="px-4 py-3">Namespace</th>
                    <th className="px-4 py-3">Keys</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {data.namespaces.map((ns) => (
                    <tr key={ns.prefix} className="border-t border-[var(--border)]">
                      <td className="px-4 py-3 font-mono text-xs">{ns.prefix}</td>
                      <td className="px-4 py-3">{ns.key_count}</td>
                      <td className="px-4 py-3 text-right">
                        <Button variant="danger" size="sm" onClick={() => setFlushTarget(ns.prefix)} disabled={ns.key_count === 0}>
                          Flush
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : (
            <EmptyState title="No cache namespaces" />
          )}
        </>
      ) : null}

      <ConfirmDialog
        open={flushTarget !== null}
        onClose={() => setFlushTarget(null)}
        onConfirm={() => void confirmFlush()}
        title="Flush cache namespace"
        message={`Delete all cached keys under "${flushTarget}"? Results will be recomputed on next access.`}
        confirmLabel="Flush"
        danger
      />
    </div>
  );
}
