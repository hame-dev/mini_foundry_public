"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { API_BASE, apiFetch } from "@/lib/api";
import { ResourceHeader, ResourceToolbar } from "@/components/foundry/FoundryPrimitives";

type Job = {
  id: string;
  job_type: string;
  status: string;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
  progress: { percent?: number; message?: string | null } | null;
  resource_type: string | null;
  resource_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

type JobLog = {
  id: string;
  level: string;
  message: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};

const phases = ["Queued", "Waited in resource queue", "Initialized runtime", "Ran", "Succeeded"];

export default function BuildsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<JobLog[]>([]);

  useEffect(() => {
    apiFetch<Job[]>("/jobs?limit=100")
      .then((rows) => {
        setJobs(rows);
        setSelectedId((prev) => prev ?? rows[0]?.id ?? null);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selectedId || typeof EventSource === "undefined") return;
    setLogs([]);
    const source = new EventSource(`${API_BASE}/jobs/${selectedId}/stream`, { withCredentials: true });
    source.addEventListener("status", (event) => {
      try {
        const next = JSON.parse((event as MessageEvent).data) as Job;
        setJobs((current) => current.map((job) => job.id === next.id ? { ...job, ...next } : job));
      } catch {
        // Ignore malformed stream events; list refresh still works.
      }
    });
    source.addEventListener("log", (event) => {
      try {
        const log = JSON.parse((event as MessageEvent).data) as JobLog;
        setLogs((current) => current.some((item) => item.id === log.id) ? current : [...current, log]);
      } catch {
        // Ignore malformed stream events.
      }
    });
    source.addEventListener("done", () => source.close());
    return () => source.close();
  }, [selectedId]);

  const selected = useMemo(() => jobs.find((j) => j.id === selectedId) ?? jobs[0] ?? null, [jobs, selectedId]);
  const duration = selected?.started_at && selected.finished_at
    ? Math.max(1, Math.round((new Date(selected.finished_at).getTime() - new Date(selected.started_at).getTime()) / 1000))
    : null;

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <ResourceHeader
        eyebrow="Builds"
        title={selected ? `Build of ${selected.resource_type ?? selected.job_type}` : "Builds"}
        subtitle="Inspect long-running dataset, pipeline, notebook, and model builds with progress, stages, and runtime details."
        tabs={[{ label: "Build info", id: "Build info" }, { label: "Spark details", id: "Spark details" }, { label: "Logs", id: "Logs" }]}
        activeTab="Build info"
      />
      <ResourceToolbar>
        <button className="btn-ghost">Refresh</button>
        <button className="btn-ghost">Queued</button>
        <button className="btn-ghost">Running</button>
        <button className="btn-ghost">Succeeded</button>
        <button className="btn-ghost">Failed</button>
      </ResourceToolbar>
      {error ? <div className="app-card" style={{ padding: 12, color: "var(--danger)" }}>Load failed: {error}</div> : null}
      <div style={{ display: "grid", gridTemplateColumns: "290px minmax(0, 1fr)", minHeight: 560, border: "1px solid var(--line)", background: "var(--panel)" }}>
        <aside style={{ borderRight: "1px solid var(--line)", padding: 18, display: "grid", alignContent: "start", gap: 12 }}>
          <h2 style={{ margin: 0, fontSize: 14 }}>Build info</h2>
          {selected ? (
            <>
              <Info label="Status" value={selected.status} badge />
              <Info label="Duration" value={duration ? `${duration}s` : "Running"} />
              <Info label="Estimated" value={duration ? `${Math.max(1, duration - 4)}s` : "Calculating"} />
              <Info label="Started" value={selected.started_at ? new Date(selected.started_at).toLocaleString() : "--"} />
              <Info label="Ended" value={selected.finished_at ? new Date(selected.finished_at).toLocaleString() : "--"} />
              <Info label="Progress" value={`${selected.status === "succeeded" ? "1 of 1" : "0 of 1"} job succeeded`} />
              <Info label="Build ID" value={selected.id.slice(0, 18)} mono />
            </>
          ) : <div style={{ color: "var(--muted)" }}>No builds yet.</div>}
        </aside>
        <main style={{ minWidth: 0 }}>
          <section style={{ padding: 18, borderBottom: "1px solid var(--line)" }}>
            <h2 style={{ margin: "0 0 18px", fontSize: 14 }}>Build progress</h2>
            <div style={{ height: 52, borderLeft: "1px solid var(--line)", position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", left: 36, right: 0, top: 18, height: 14, background: selected?.status === "failed" ? "var(--danger)" : "#6dcc95" }} />
              <div style={{ position: "absolute", left: 36, right: 0, bottom: 0, display: "flex", justifyContent: "space-between", color: "var(--muted)", fontSize: 11 }}>
                {["00:00", "00:15", "00:30", "00:45", "01:00"].map((t) => <span key={t}>{t}</span>)}
              </div>
            </div>
          </section>
          <section style={{ padding: 0 }}>
            <table>
              <thead><tr><th>Resource</th><th>Start time</th><th>Duration</th></tr></thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id} onClick={() => setSelectedId(job.id)} style={{ cursor: "pointer", background: selected?.id === job.id ? "var(--accent-soft)" : undefined }}>
                    <td>
                      <b>{job.resource_type ?? job.job_type}</b>
                      <div className="font-mono" style={{ color: "var(--muted)", fontSize: 11 }}>{job.resource_id ?? job.id}</div>
                      <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 10 }}>
                        {phases.map((phase, i) => (
                          <div key={phase} style={{ borderTop: `4px solid ${job.status === "failed" && i === 3 ? "var(--danger)" : "var(--success)"}`, paddingTop: 6 }}>
                            <div style={{ fontWeight: 600, fontSize: 12 }}>{phase}</div>
                            <div style={{ color: "var(--muted)", fontSize: 11 }}>{i === 0 ? "Started job" : i === 4 ? job.status : "Details"}</div>
                          </div>
                        ))}
                      </div>
                    </td>
                    <td>{job.started_at ? new Date(job.started_at).toLocaleString() : "--"}</td>
                    <td>{job.started_at && job.finished_at ? `${Math.round((new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) / 1000)}s` : "--"}</td>
                  </tr>
                ))}
                {!jobs.length ? <tr><td colSpan={3}><div className="empty-state"><div className="empty-state-title">No builds yet</div></div></td></tr> : null}
              </tbody>
            </table>
          </section>
          {selected ? (
            <section style={{ padding: 16, borderTop: "1px solid var(--line)" }}>
              <Link className="btn-ghost" href="/admin/jobs">Open in Jobs</Link>
              {selected.error ? <pre style={{ marginTop: 12 }}>{selected.error}</pre> : null}
              <div className="mt-4 rounded border border-[var(--line-soft)]">
                <div className="border-b border-[var(--line-soft)] px-3 py-2 text-xs font-semibold uppercase text-[var(--muted)]">Live logs</div>
                <div style={{ maxHeight: 220, overflow: "auto" }}>
                  {logs.length ? logs.map((log) => (
                    <div key={log.id} className="border-b border-[var(--line-soft)] px-3 py-2 font-mono text-xs">
                      <span className="text-[var(--muted)]">{new Date(log.created_at).toLocaleTimeString()} </span>
                      <span className={log.level === "error" ? "text-[var(--danger)]" : ""}>{log.level}</span>
                      <span> · {log.message}</span>
                    </div>
                  )) : <div className="px-3 py-4 text-sm text-[var(--muted)]">Waiting for streamed log events.</div>}
                </div>
              </div>
            </section>
          ) : null}
        </main>
      </div>
    </div>
  );
}

function Info({ label, value, badge = false, mono = false }: { label: string; value: string; badge?: boolean; mono?: boolean }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "90px 1fr", gap: 10, alignItems: "center" }}>
      <span style={{ color: "var(--text-2)", fontWeight: 600 }}>{label}</span>
      {badge ? <span className="badge badge-success">{value}</span> : <span className={mono ? "font-mono" : ""}>{value}</span>}
    </div>
  );
}
