"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { PipelineDetail, PipelineSummary } from "@/lib/pipelines";

export default function PipelinesListPage() {
  const router = useRouter();
  const [items, setItems] = useState<PipelineSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    apiFetch<PipelineSummary[]>("/pipelines")
      .then(setItems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function createNew() {
    setCreating(true);
    try {
      const created = await apiFetch<PipelineDetail>("/pipelines", {
        method: "POST",
        body: JSON.stringify({ name: "Untitled pipeline" }),
      });
      router.push(`/pipelines/${created.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "create failed");
      setCreating(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header-eyebrow">Build · Pipelines</div>
          <h1 className="page-header-title">Pipeline builder</h1>
          <div className="page-header-subtitle">
            Drag datasets onto the canvas, connect them with joins / filters / formulas, and
            materialize a derived dataset for dashboards and notebooks.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn-primary" onClick={createNew} disabled={creating}>
            <span aria-hidden>＋</span>
            <span>{creating ? "Creating…" : "New pipeline"}</span>
          </button>
        </div>
      </div>

      {loading ? (
        <div className="app-card empty-state">
          <div className="empty-state-title">Loading pipelines…</div>
        </div>
      ) : error ? (
        <div className="app-card empty-state">
          <div className="empty-state-title" style={{ color: "var(--danger)" }}>
            Failed to load pipelines
          </div>
          <div className="empty-state-help">{error}</div>
        </div>
      ) : (
        <div className="app-card overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>AI policy</th>
                <th>Output dataset</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={5}>
                    <div className="empty-state">
                      <div className="empty-state-title">No pipelines yet</div>
                      <div className="empty-state-help">
                        Click <strong>New pipeline</strong> to start a canvas.
                      </div>
                    </div>
                  </td>
                </tr>
              ) : (
                items.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link href={`/pipelines/${p.id}`} className="text-blue-600 hover:underline">
                        {p.name}
                      </Link>
                      {p.description ? (
                        <div style={{ color: "var(--muted-2)", fontSize: 11.5, marginTop: 2 }}>
                          {p.description}
                        </div>
                      ) : null}
                    </td>
                    <td>
                      {p.last_run_status === "ok" ? (
                        <span className="badge badge-success">ran ok</span>
                      ) : p.last_run_status === "error" ? (
                        <span className="badge badge-danger">error</span>
                      ) : (
                        <span className="badge">draft</span>
                      )}
                    </td>
                    <td>
                      <span className="badge badge-accent">{p.ai_policy}</span>
                    </td>
                    <td>
                      {p.output_dataset_id ? (
                        <Link href={`/catalog/${p.output_dataset_id}`} className="text-blue-600 hover:underline">
                          open ↗
                        </Link>
                      ) : (
                        <span style={{ color: "var(--muted-2)" }}>—</span>
                      )}
                    </td>
                    <td style={{ color: "var(--muted)" }}>
                      {new Date(p.updated_at).toLocaleString()}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
