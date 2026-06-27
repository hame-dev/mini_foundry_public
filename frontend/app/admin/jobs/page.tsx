"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Job = {
  id: string;
  user_id: string | null;
  job_type: string;
  status: string;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
  progress: { percent: number; message: string | null } | null;
  resource_type: string | null;
  resource_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

const STATUS_COLOR: Record<string, string> = {
  queued: "badge",
  running: "badge badge-accent",
  succeeded: "badge badge-success",
  failed: "badge badge-danger",
  cancelled: "badge badge-warning",
  timed_out: "badge badge-warning",
};

export default function AdminJobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Job | null>(null);

  useEffect(() => {
    const tick = async () => {
      try {
        const data = await apiFetch<Job[]>("/jobs?limit=100");
        setJobs(data);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : String(e));
      }
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    const tick = async () => {
      try {
        const j = await apiFetch<Job>(`/jobs/${selectedId}`);
        setSelected(j);
      } catch {}
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [selectedId]);

  async function cancel(id: string) {
    try {
      await apiFetch(`/jobs/${id}/cancel`, { method: "POST" });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function retry(id: string) {
    try {
      const j = await apiFetch<Job>(`/jobs/${id}/retry`, { method: "POST" });
      setSelected(j);
      setJobs((rows) => rows.map((row) => row.id === j.id ? j : row));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-7 space-y-3">
        <h1 className="text-2xl font-semibold">Jobs</h1>
        {error && <div className="text-red-600 text-sm">{error}</div>}
        <div className="app-card overflow-hidden">
        <table className="data-table">
          <thead>
            <tr>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Created</th>
              <th className="px-3 py-2">Duration</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}
                onClick={() => setSelectedId(j.id)}
                style={selectedId === j.id ? { background: "var(--accent-soft)" } : undefined}
                className={`border-t cursor-pointer hover:bg-gray-50`}>
                <td className="px-3 py-2 font-mono">{j.job_type}</td>
                <td className="px-3 py-2">
                  <span className={STATUS_COLOR[j.status] || "badge"}>{j.status}</span>
                </td>
                <td className="px-3 py-2 text-gray-500">{new Date(j.created_at).toLocaleString()}</td>
                <td className="px-3 py-2 text-gray-500">
                  {j.started_at && j.finished_at
                    ? `${Math.round((new Date(j.finished_at).getTime() - new Date(j.started_at).getTime()) / 1000)}s`
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      <aside className="col-span-5 app-card p-4 max-h-[80vh] overflow-auto space-y-3">
        {selected ? (
          <>
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">{selected.job_type}</h2>
              <span className={`text-xs ${STATUS_COLOR[selected.status] || "badge"}`}>{selected.status}</span>
            </div>
            <div className="text-xs text-gray-500 font-mono">{selected.id}</div>
            {selected.progress && (
              <div className="text-xs">
                Progress: {Math.round(selected.progress.percent)}% {selected.progress.message ? `— ${selected.progress.message}` : ""}
              </div>
            )}
            <Section title="Input" body={selected.input} />
            <Section title="Output" body={selected.output} />
            {selected.error && (
              <div>
                <h3 className="text-xs uppercase tracking-wide text-gray-500 mb-1">Error</h3>
                <pre className="text-xs bg-red-50 border border-red-200 rounded p-2 whitespace-pre-wrap">{selected.error}</pre>
              </div>
            )}
            {(selected.status === "queued" || selected.status === "running") && (
              <button onClick={() => cancel(selected.id)}
                className="w-full border border-red-200 text-red-600 rounded py-1 text-sm hover:bg-red-50">
                Cancel
              </button>
            )}
            {(selected.status === "queued" || selected.status === "failed" || selected.status === "timed_out") && (
              <button onClick={() => retry(selected.id)}
                className="w-full border border-slate-300 text-slate-700 rounded py-1 text-sm hover:bg-slate-50">
                Retry
              </button>
            )}
          </>
        ) : (
          <div className="text-sm text-gray-500">Select a job to inspect it.</div>
        )}
      </aside>
    </div>
  );
}

function Section({ title, body }: { title: string; body: unknown }) {
  return (
    <div>
      <h3 className="text-xs uppercase tracking-wide text-gray-500 mb-1">{title}</h3>
      <pre className="text-xs bg-gray-50 border rounded p-2 max-h-40 overflow-auto">
        {body ? JSON.stringify(body, null, 2) : "—"}
      </pre>
    </div>
  );
}
