"use client";

import { useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { Select } from "@/components/foundry";
import { operationsApi, type Metrics } from "@/lib/api/endpoints/operations";
import { ApiError } from "@/lib/api";

const WINDOWS = [
  { label: "Last 1 hour", value: 1 },
  { label: "Last 24 hours", value: 24 },
  { label: "Last 7 days", value: 168 },
];

export default function OperationsMetricsPage() {
  const [data, setData] = useState<Metrics | null>(null);
  const [windowHours, setWindowHours] = useState(24);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (hours: number) => {
    setLoading(true);
    setError(null);
    try {
      setData(await operationsApi.metrics(hours));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load metrics.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(windowHours);
  }, [load, windowHours]);

  return (
    <div className="space-y-5">
      <ResourceHeader
        title="Metrics"
        type="Operations"
        status={data ? "Live" : "Loading"}
        actions={
          <Select value={windowHours} onChange={(e) => setWindowHours(Number(e.target.value))}>
            {WINDOWS.map((w) => (
              <option key={w.value} value={w.value}>
                {w.label}
              </option>
            ))}
          </Select>
        }
      />

      {loading ? <LoadingState label="Aggregating metrics..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && !error && data ? (
        <>
          <section className="grid gap-3 md:grid-cols-3">
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Total events</p>
              <p className="mt-2 text-2xl font-semibold">{data.total_events}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Errors / denials</p>
              <p className="mt-2 text-2xl font-semibold text-red-300">{data.error_events}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Window</p>
              <p className="mt-2 text-2xl font-semibold">{data.window_hours}h</p>
            </div>
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="app-card overflow-hidden">
              <header className="px-4 py-3 text-sm font-semibold">Events by type</header>
              {data.event_counts.length ? (
                <table className="w-full text-sm">
                  <tbody>
                    {data.event_counts.map((e) => (
                      <tr key={e.event_type} className="border-t border-[var(--border)]">
                        <td className="px-4 py-2 font-mono text-xs">{e.event_type}</td>
                        <td className="px-4 py-2 text-right">{e.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <EmptyState title="No events in window" />
              )}
            </section>

            <section className="app-card overflow-hidden">
              <header className="px-4 py-3 text-sm font-semibold">Latency by resource</header>
              {data.latency.length ? (
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase tracking-wide text-[var(--muted)]">
                    <tr>
                      <th className="px-4 py-2">Resource</th>
                      <th className="px-4 py-2 text-right">Count</th>
                      <th className="px-4 py-2 text-right">Avg ms</th>
                      <th className="px-4 py-2 text-right">Max ms</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.latency.map((l) => (
                      <tr key={l.resource_type} className="border-t border-[var(--border)]">
                        <td className="px-4 py-2">{l.resource_type}</td>
                        <td className="px-4 py-2 text-right">{l.count}</td>
                        <td className="px-4 py-2 text-right">{l.avg_ms.toFixed(0)}</td>
                        <td className="px-4 py-2 text-right">{l.max_ms}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <EmptyState title="No latency samples" detail="No usage metrics recorded in this window." />
              )}
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}
