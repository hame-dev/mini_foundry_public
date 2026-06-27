"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { StatusPill } from "@/components/platform/StatusPill";
import { operationsApi, type Hardening } from "@/lib/api/endpoints/operations";
import { ApiError } from "@/lib/api";

type HealthCheck = {
  status: string;
  detail?: string;
  exists?: boolean;
  [key: string]: unknown;
};

type HealthResponse = {
  status: string;
  checks: Record<string, HealthCheck>;
};

function statusClass(status: string) {
  if (status === "ok") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-200";
  if (status === "not_configured") return "border-amber-300/30 bg-amber-300/10 text-amber-100";
  return "border-red-400/30 bg-red-400/10 text-red-200";
}

function formatName(name: string) {
  return name.replaceAll("_", " ");
}

function safeDetail(check: HealthCheck) {
  const detail = typeof check.detail === "string" ? check.detail : "";
  if (!detail) return "No detail reported.";
  return detail.length > 220 ? `${detail.slice(0, 220)}...` : detail;
}

export default function OperationsHealthPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [hardening, setHardening] = useState<Hardening | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);

  const loadHealth = useCallback(async (quiet = false) => {
    if (quiet) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const [healthData, hardeningData] = await Promise.all([
        operationsApi.health(),
        operationsApi.hardening().catch(() => null),
      ]);
      setHealth(healthData);
      setHardening(hardeningData);
      setLastCheckedAt(new Date());
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Unable to load system health.";
      setError(message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadHealth();
    const timer = window.setInterval(() => {
      void loadHealth(true);
    }, 30000);
    return () => window.clearInterval(timer);
  }, [loadHealth]);

  const checks = useMemo(() => Object.entries(health?.checks ?? {}), [health]);
  const counts = useMemo(() => {
    return checks.reduce(
      (acc, [, check]) => {
        if (check.status === "ok") acc.ok += 1;
        else if (check.status === "not_configured") acc.notConfigured += 1;
        else acc.unhealthy += 1;
        return acc;
      },
      { ok: 0, notConfigured: 0, unhealthy: 0 },
    );
  }, [checks]);

  return (
    <div className="space-y-5">
      <ResourceHeader
        title="System health"
        type="Operations"
        status={health?.status ?? "Loading"}
        actions={
          <button
            type="button"
            className="toolbar-button"
            onClick={() => void loadHealth(true)}
            disabled={refreshing}
            title="Refresh health checks"
          >
            {refreshing ? "Refreshing" : "Refresh"}
          </button>
        }
      />

      {loading ? <LoadingState label="Checking platform services..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && !error && health ? (
        <>
          <section className="grid gap-3 md:grid-cols-4">
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Overall</p>
              <div className="mt-3">
                <StatusPill status={health.status} />
              </div>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Healthy</p>
              <p className="mt-2 text-2xl font-semibold">{counts.ok}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Needs config</p>
              <p className="mt-2 text-2xl font-semibold">{counts.notConfigured}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Unhealthy</p>
              <p className="mt-2 text-2xl font-semibold">{counts.unhealthy}</p>
            </div>
          </section>

          {checks.length ? (
            <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {checks.map(([name, check]) => (
                <article key={name} className="app-card p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h2 className="font-semibold capitalize">{formatName(name)}</h2>
                      <p className="mt-1 text-sm text-[var(--muted)]">{safeDetail(check)}</p>
                    </div>
                    <span className={`rounded-full border px-2 py-1 text-xs ${statusClass(check.status)}`}>{check.status}</span>
                  </div>
                  <dl className="mt-4 grid gap-2 text-xs text-[var(--muted)]">
                    {Object.entries(check)
                      .filter(([key]) => !["status", "detail"].includes(key))
                      .map(([key, value]) => (
                        <div key={key} className="flex items-center justify-between gap-3">
                          <dt className="capitalize">{formatName(key)}</dt>
                          <dd className="max-w-[65%] truncate text-right text-[var(--text)]">{String(value)}</dd>
                        </div>
                      ))}
                  </dl>
                </article>
              ))}
            </section>
          ) : (
            <EmptyState title="No health checks reported" detail="The backend responded without component checks." />
          )}

          {hardening ? (
            <section className="app-card p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold">Production hardening</h2>
                  <p className="mt-1 text-sm text-[var(--muted)]">
                    Environment {hardening.environment}; enforcement {hardening.enforced ? "enabled" : "disabled"}.
                  </p>
                </div>
                <StatusPill status={hardening.status} />
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-4">
                <Check label="Bearer auth" ok={!hardening.bearer_auth_enabled} detail={hardening.bearer_auth_enabled ? "enabled" : "disabled"} />
                <Check label="Backup drill" ok={hardening.backup_restore_verified} detail={hardening.backup_restore_verified ? "verified" : "not verified"} />
                <Check label="Alerting" ok={hardening.metrics_alerting_configured} detail={hardening.metrics_alerting_configured ? "configured" : "not configured"} />
                <Check label="Sandbox host" ok={hardening.rootless_sandbox_host} detail={hardening.rootless_sandbox_host ? "rootless" : "not rootless"} />
              </div>
              {hardening.issues.length ? (
                <ul className="mt-4 space-y-1 text-sm text-amber-100">
                  {hardening.issues.map((issue) => <li key={issue}>{issue}</li>)}
                </ul>
              ) : null}
            </section>
          ) : null}

          <p className="text-xs text-[var(--muted)]">
            Last checked {lastCheckedAt ? lastCheckedAt.toLocaleTimeString() : "unknown"}. This page refreshes every 30 seconds.
          </p>
        </>
      ) : null}
    </div>
  );
}

function Check({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <div className="rounded border border-[var(--line)] bg-[var(--panel-2)] p-3">
      <p className="text-xs uppercase tracking-wide text-[var(--muted)]">{label}</p>
      <p className={ok ? "mt-1 text-sm text-emerald-200" : "mt-1 text-sm text-amber-100"}>{detail}</p>
    </div>
  );
}
