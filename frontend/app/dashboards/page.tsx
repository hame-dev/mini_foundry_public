"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { DashboardSummary } from "@/lib/dashboards";

export default function DashboardsListPage() {
  const [items, setItems] = useState<DashboardSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<DashboardSummary[]>("/dashboards")
      .then(setItems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function remove(id: string) {
    if (!confirm("Delete this dashboard?")) return;
    await apiFetch(`/dashboards/${id}`, { method: "DELETE" });
    setItems((prev) => prev.filter((d) => d.id !== id));
  }

  if (loading) return <div>Loading...</div>;
  if (error) return <div className="text-red-600">{error}</div>;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">Dashboards</h1>
        <Link href="/dashboards/new" className="btn-primary text-sm">
          + New dashboard
        </Link>
      </div>
      <div className="app-card overflow-hidden">
        <table className="data-table">
          <thead>
            <tr>
              <th className="px-4 py-2">Title</th>
              <th className="px-4 py-2">Description</th>
              <th className="px-4 py-2">Updated</th>
              <th className="px-4 py-2">Published</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr>
                <td colSpan={5}>
                  <div className="empty-state">
                    <div className="empty-state-title">No dashboards yet.</div>
                    <div className="empty-state-help">Create your first dashboard to get started.</div>
                  </div>
                </td>
              </tr>
            )}
            {items.map((d) => (
              <tr key={d.id}>
                <td>
                  <Link href={`/dashboards/${d.id}`} style={{ color: "var(--accent)" }} className="hover:underline">{d.title}</Link>
                </td>
                <td>{d.description || "—"}</td>
                <td>{new Date(d.updated_at).toLocaleString()}</td>
                <td>
                  {d.published_at ? (
                    <span className="badge badge-success">v{d.published_version}</span>
                  ) : (
                    <span className="badge">Draft</span>
                  )}
                </td>
                <td style={{ textAlign: "right" }}>
                  <button className="btn-ghost" onClick={() => remove(d.id)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
