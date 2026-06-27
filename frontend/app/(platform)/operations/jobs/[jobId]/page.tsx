"use client";

import { use, useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { ErrorState, LoadingState } from "@/components/platform/States";
import { Button, StatusPill } from "@/components/foundry";
import { operationsApi, type Job, type JobDetail } from "@/lib/api/endpoints/operations";
import { ApiError } from "@/lib/api";

const ACTIVE = new Set(["queued", "running", "pending", "started"]);
const RETRYABLE = new Set(["failed", "canceled", "cancelled"]);

function JsonBlock({ title, value }: { title: string; value: unknown }) {
  if (value === null || value === undefined) return null;
  return (
    <section className="app-card p-4">
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      <pre className="overflow-x-auto rounded bg-black/20 p-3 text-xs text-[var(--muted)]">
        {JSON.stringify(value, null, 2)}
      </pre>
    </section>
  );
}

export default function JobDetailPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = use(params);
  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (quiet = false) => {
      if (!quiet) setLoading(true);
      setError(null);
      try {
        setJob(await operationsApi.jobDetail(jobId));
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Unable to load job.");
      } finally {
        setLoading(false);
      }
    },
    [jobId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Poll while the job is still active.
  useEffect(() => {
    if (!job || !ACTIVE.has(job.status)) return;
    const timer = window.setInterval(() => void load(true), 5000);
    return () => window.clearInterval(timer);
  }, [job, load]);

  async function act(fn: () => Promise<Job>) {
    setBusy(true);
    setError(null);
    try {
      const next = await fn();
      setJob((prev) => prev ? { ...prev, ...next } : { ...next, attempts: [], log_events: [] });
      void load(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader
        title={job ? job.job_type : "Job"}
        type="Operations / Job"
        status={job?.status ?? "Loading"}
        subtitle={job ? job.id : undefined}
        actions={
          job ? (
            <div className="flex gap-2">
              {ACTIVE.has(job.status) ? (
                <Button variant="danger" size="sm" loading={busy} onClick={() => void act(() => operationsApi.cancelJob(jobId))}>
                  Cancel
                </Button>
              ) : null}
              {RETRYABLE.has(job.status) ? (
                <Button size="sm" loading={busy} onClick={() => void act(() => operationsApi.retryJob(jobId))}>
                  Retry
                </Button>
              ) : null}
            </div>
          ) : null
        }
      />

      {loading ? <LoadingState label="Loading job..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && job ? (
        <>
          <section className="grid gap-3 md:grid-cols-4">
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Status</p>
              <div className="mt-2">
                <StatusPill status={job.status} />
              </div>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Created</p>
              <p className="mt-2 text-sm">{new Date(job.created_at).toLocaleString()}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Started</p>
              <p className="mt-2 text-sm">{job.started_at ? new Date(job.started_at).toLocaleString() : "—"}</p>
            </div>
            <div className="app-card p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">Finished</p>
              <p className="mt-2 text-sm">{job.finished_at ? new Date(job.finished_at).toLocaleString() : "—"}</p>
            </div>
          </section>

          {job.resource_type ? (
            <p className="text-xs text-[var(--muted)]">
              Resource: {job.resource_type}
              {job.resource_id ? ` · ${job.resource_id}` : ""}
            </p>
          ) : null}

          {job.error ? (
            <section className="app-card border border-red-400/30 p-4">
              <h2 className="mb-2 text-sm font-semibold text-red-300">Error</h2>
              <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-red-200">{job.error}</pre>
            </section>
          ) : null}

          <JsonBlock title="Progress" value={job.progress} />
          <JsonBlock title="Input" value={job.input} />
          <JsonBlock title="Output" value={job.output} />

          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="text-sm font-semibold">Attempts</h2>
            </div>
            {job.attempts.length ? (
              <table className="data-table text-sm">
                <thead>
                  <tr>
                    <th>Attempt</th>
                    <th>Status</th>
                    <th>Task id</th>
                    <th>Started</th>
                    <th>Finished</th>
                  </tr>
                </thead>
                <tbody>
                  {job.attempts.map((attempt) => (
                    <tr key={attempt.id}>
                      <td>{attempt.attempt_number}</td>
                      <td><StatusPill status={attempt.status} /></td>
                      <td className="font-mono text-xs">{attempt.celery_task_id ?? "—"}</td>
                      <td>{attempt.started_at ? new Date(attempt.started_at).toLocaleString() : "—"}</td>
                      <td>{attempt.finished_at ? new Date(attempt.finished_at).toLocaleString() : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-4 text-sm text-[var(--muted)]">No attempts recorded.</div>
            )}
          </section>

          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="text-sm font-semibold">Log events</h2>
            </div>
            {job.log_events.length ? (
              <table className="data-table text-sm">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Level</th>
                    <th>Message</th>
                    <th>Payload</th>
                  </tr>
                </thead>
                <tbody>
                  {job.log_events.map((event) => (
                    <tr key={event.id}>
                      <td>{new Date(event.created_at).toLocaleString()}</td>
                      <td>{event.level}</td>
                      <td>{event.message}</td>
                      <td className="font-mono text-xs">{event.payload ? JSON.stringify(event.payload) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-4 text-sm text-[var(--muted)]">No log events recorded.</div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
