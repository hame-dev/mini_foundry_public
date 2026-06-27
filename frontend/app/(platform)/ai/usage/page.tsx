"use client";

import { useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { aiApi, type AiUsage } from "@/lib/api/endpoints/ai";
import { ApiError } from "@/lib/api";

const WINDOWS = [
  { label: "Last 1 hour", value: 1 },
  { label: "Last 24 hours", value: 24 },
  { label: "Last 7 days", value: 168 },
];

export default function AiUsagePage() {
  const [data, setData] = useState<AiUsage | null>(null);
  const [windowHours, setWindowHours] = useState(24);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (hours: number) => {
    setLoading(true);
    setError(null);
    try {
      setData(await aiApi.usage(hours));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load AI usage.");
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
        title="AI usage"
        type="AI"
        status={data ? "Live" : "Loading"}
        actions={
          <select className="input-dark" value={windowHours} onChange={(e) => setWindowHours(Number(e.target.value))}>
            {WINDOWS.map((w) => (
              <option key={w.value} value={w.value}>{w.label}</option>
            ))}
          </select>
        }
      />

      {loading ? <LoadingState label="Aggregating AI usage..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && !error && data ? (
        <>
          <section className="grid gap-3 md:grid-cols-4">
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Runs</p>
              <p className="mt-2 text-2xl font-semibold">{data.total_runs}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Tokens (est.)</p>
              <p className="mt-2 text-2xl font-semibold">{data.total_tokens}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Credits</p>
              <p className="mt-2 text-2xl font-semibold">{data.credits.toFixed(2)}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Avg latency</p>
              <p className="mt-2 text-2xl font-semibold">{data.latency_ms_avg.toFixed(0)} ms</p>
            </div>
          </section>

          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="font-semibold">By provider &amp; model</h2>
            </div>
            {data.by_provider_model.length ? (
              <table className="w-full text-left text-sm">
                <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                  <tr>
                    <th className="px-4 py-3">Provider</th>
                    <th className="px-4 py-3">Model</th>
                    <th className="px-4 py-3 text-right">Runs</th>
                    <th className="px-4 py-3 text-right">Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_provider_model.map((r, i) => (
                    <tr key={i} className="border-t border-[var(--line-soft)]">
                      <td className="px-4 py-3">{r.provider || "—"}</td>
                      <td className="px-4 py-3">{r.model || "—"}</td>
                      <td className="px-4 py-3 text-right">{r.run_count}</td>
                      <td className="px-4 py-3 text-right">{r.token_total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-4"><EmptyState title="No AI runs in window" /></div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
