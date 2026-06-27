"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Card, StatusPill } from "@/components/foundry/controls";
import { EmptyState, ErrorState, LoadingState } from "@/components/foundry/feedback";
import { statusTone } from "@/lib/status";

type Job = {
  id: string;
  job_type: string;
  status: string;
  resource_type: string | null;
  resource_id: string | null;
  created_at: string;
  finished_at: string | null;
};

type Health = {
  status: string;
  checks: Record<string, { status: string; detail?: string }>;
};

const QUICK_LINKS: { href: string; label: string; mark: string; hint: string }[] = [
  { href: "/data/catalog", label: "Data Catalog", mark: "DA", hint: "Browse governed datasets" },
  { href: "/build/pipelines", label: "Pipelines", mark: "PL", hint: "Build and run transforms" },
  { href: "/ontology/explorer", label: "Object Explorer", mark: "OE", hint: "Investigate objects" },
  { href: "/apps/dashboards", label: "Dashboards", mark: "DB", hint: "Analytical views" },
  { href: "/analytics/sql", label: "SQL", mark: "SQ", hint: "Query the platform" },
  { href: "/governance/audit", label: "Audit", mark: "AU", hint: "Review activity" },
];

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export default function HomePage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError(false);
    try {
      const [jobsRes, healthRes] = await Promise.allSettled([
        apiFetch<Job[]>("/jobs?limit=50", { cache: "no-store" }),
        apiFetch<Health>("/system/health", { cache: "no-store" }),
      ]);
      if (jobsRes.status === "fulfilled") setJobs(jobsRes.value);
      else setJobs([]);
      if (healthRes.status === "fulfilled") setHealth(healthRes.value);
      if (jobsRes.status === "rejected" && healthRes.status === "rejected") setError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    apiFetch<{ email: string }>("/auth/me").then((u) => setEmail(u.email)).catch(() => setEmail(null));
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const failed = (jobs ?? []).filter((j) =>
    ["failed", "error", "canceled", "cancelled"].includes(j.status.toLowerCase()),
  );
  const recent = (jobs ?? []).slice(0, 6);
  const greeting = email ? `Welcome back, ${email.split("@")[0]}` : "Welcome to Mini Foundry";

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <header className="page-header">
        <div>
          <div className="page-header-eyebrow">Home</div>
          <h1 className="page-header-title">{greeting}</h1>
          <p className="page-header-subtitle">
            Your operational control plane — resources, builds, and platform health at a glance.
          </p>
        </div>
        {health ? (
          <StatusPill status={health.status === "ok" ? "Healthy" : health.status} tone={statusTone(health.status)} />
        ) : null}
      </header>

      {/* Quick launch */}
      <section className="home-quicklinks">
        {QUICK_LINKS.map((q) => (
          <Link key={q.href} href={q.href} className="home-quicklink">
            <span className="home-quicklink-mark">{q.mark}</span>
            <span className="home-quicklink-text">
              <strong>{q.label}</strong>
              <span>{q.hint}</span>
            </span>
          </Link>
        ))}
      </section>

      {error ? (
        <Card title="Home">
          <ErrorState description="Could not reach the platform API. Check that the backend is running." onRetry={load} />
        </Card>
      ) : (
        <div className="home-grid">
          <Card title="Recent activity">
            {loading ? (
              <LoadingState label="Loading activity…" />
            ) : recent.length === 0 ? (
              <EmptyState title="No recent activity" description="Jobs and builds you run will appear here." />
            ) : (
              <ul className="home-list">
                {recent.map((j) => (
                  <li key={j.id} className="home-list-item">
                    <StatusPill status={j.status} tone={statusTone(j.status)} />
                    <span className="home-list-main">
                      <strong>{j.resource_type ?? j.job_type}</strong>
                      <span>{j.resource_id ?? j.job_type}</span>
                    </span>
                    <span className="home-list-meta">{relativeTime(j.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Recently failed builds">
            {loading ? (
              <LoadingState label="Loading builds…" rows={2} />
            ) : failed.length === 0 ? (
              <EmptyState title="All clear" description="No failed or canceled builds recently." />
            ) : (
              <ul className="home-list">
                {failed.slice(0, 6).map((j) => (
                  <li key={j.id} className="home-list-item">
                    <StatusPill status={j.status} tone={statusTone(j.status)} />
                    <span className="home-list-main">
                      <strong>{j.resource_type ?? j.job_type}</strong>
                      <span>{j.resource_id ?? j.id}</span>
                    </span>
                    <Link href="/build/runs" className="home-list-meta home-list-link">
                      View
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="System health">
            {health ? (
              <ul className="home-health">
                {Object.entries(health.checks).map(([name, check]) => (
                  <li key={name} className="home-health-item">
                    <StatusPill status={check.status} tone={statusTone(check.status)} />
                    <span className="home-health-name">{name}</span>
                    {check.detail ? <span className="home-health-detail">{check.detail}</span> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <LoadingState label="Checking services…" rows={3} />
            )}
          </Card>

          <Card title="Assigned tasks">
            <EmptyState title="No tasks assigned" description="Action items and approvals routed to you will show up here." />
          </Card>

          <Card title="Favorites">
            <EmptyState
              title="No favorites yet"
              description="Star datasets, pipelines, and apps to pin them here."
              action={
                <Link href="/data/catalog" className="home-list-link">
                  Browse catalog →
                </Link>
              }
            />
          </Card>

          <Card title="Alerts">
            <EmptyState title="No active alerts" description="Quality and freshness alerts will appear here." />
          </Card>
        </div>
      )}
    </div>
  );
}
