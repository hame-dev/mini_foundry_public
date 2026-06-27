"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ResourceHeader, ResourceToolbar } from "@/components/foundry/FoundryPrimitives";
import { apiFetch } from "@/lib/api";

type ConnectorDataset = {
  id: string;
  name: string;
  table_name: string;
  row_count: number | null;
  execution_engine: string;
  ai_policy: string;
};

type ConnectorJob = {
  id: string;
  job_type: string;
  status: string;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};

type Connector = {
  id: string;
  name: string;
  source_type: string;
  status: string;
  created_at: string;
  updated_at: string;
  config: Record<string, unknown>;
  datasets: ConnectorDataset[];
  latest_job: ConnectorJob | null;
  supported_actions: string[];
};

const statusClass: Record<string, string> = {
  ok: "badge-success",
  discovering: "badge-warning",
  error: "badge-danger",
  failed: "badge-danger",
};

export default function ConnectorsPage() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    apiFetch<Connector[]>("/connectors")
      .then(setConnectors)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function sync(id: string) {
    setSyncing(id);
    setError(null);
    try {
      await apiFetch(`/connectors/${id}/sync`, { method: "POST" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSyncing(null);
    }
  }

  return (
    <div className="space-y-4">
      <ResourceHeader
        eyebrow="Data Integration"
        title="Connectors"
        subtitle="Inspect registered sources, loaded datasets, sync status, and recent discovery or profiling jobs."
        tabs={[{ label: "Sources", id: "Sources" }, { label: "Datasets", id: "Datasets" }, { label: "Jobs", id: "Jobs" }]}
        activeTab="Sources"
      />
      <ResourceToolbar>
        <button className="btn-ghost" onClick={load} disabled={loading}>Refresh</button>
        <Link href="/connectors/new" className="btn-primary text-sm">New connector</Link>
      </ResourceToolbar>

      {error && <div className="app-card p-3 text-sm text-red-600">{error}</div>}

      <div className="app-card overflow-hidden">
        <table className="data-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Type</th>
              <th>Status</th>
              <th>Datasets</th>
              <th>Latest job</th>
              <th>Config</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} className="p-6 text-center text-sm text-gray-500">Loading connectors...</td></tr>
            ) : connectors.length === 0 ? (
              <tr><td colSpan={7} className="p-6 text-center text-sm text-gray-500">No connectors yet.</td></tr>
            ) : connectors.map((source) => (
              <tr key={source.id} className="align-top">
                <td>
                  <div className="font-semibold">{source.name}</div>
                  <div className="font-mono text-[11px] text-gray-500">{source.id.slice(0, 8)}</div>
                </td>
                <td><span className="badge">{source.source_type}</span></td>
                <td><span className={`badge ${statusClass[source.status] ?? ""}`}>{source.status}</span></td>
                <td>
                  <div className="space-y-1">
                    {source.datasets.length === 0 ? <span className="text-gray-500">none</span> : source.datasets.map((ds) => (
                      <Link key={ds.id} href={`/catalog/${ds.id}`} className="block hover:underline">
                        {ds.name}
                        <span className="ml-2 text-[11px] text-gray-500">
                          {ds.execution_engine} · {ds.row_count == null ? "unknown rows" : `${ds.row_count.toLocaleString()} rows`}
                        </span>
                      </Link>
                    ))}
                  </div>
                </td>
                <td>
                  {source.latest_job ? (
                    <Link href="/admin/jobs" className="hover:underline">
                      <span className={`badge ${statusClass[source.latest_job.status] ?? ""}`}>{source.latest_job.status}</span>
                      <div className="mt-1 text-[11px] text-gray-500">{source.latest_job.job_type}</div>
                    </Link>
                  ) : <span className="text-gray-500">none</span>}
                </td>
                <td>
                  <pre className="max-w-xs overflow-auto text-[11px] leading-5">{JSON.stringify(source.config, null, 2)}</pre>
                </td>
                <td>
                  {source.supported_actions.includes("discover_schema") ? (
                    <button className="btn-ghost text-xs" onClick={() => sync(source.id)} disabled={syncing === source.id}>
                      {syncing === source.id ? "Syncing..." : "Discover schema"}
                    </button>
                  ) : <span className="text-gray-500">No live sync</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
