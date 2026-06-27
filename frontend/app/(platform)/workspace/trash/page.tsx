"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Resource = {
  id: string;
  resource_type: string;
  name: string;
  project_id: string | null;
  owner_user_id: string | null;
  updated_at: string;
};

export default function TrashPage() {
  const [rows, setRows] = useState<Resource[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setRows(await apiFetch<Resource[]>("/platform/trash"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function restore(id: string) {
    await apiFetch(`/platform/resources/${id}/restore`, { method: "POST" });
    await load();
  }

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="app-card" style={{ padding: 16 }}>
        <div className="panel-heading" style={{ border: 0, padding: 0 }}>Trash</div>
        <div style={{ color: "var(--muted)", fontSize: 13 }}>Restore recently deleted resources before retention purge.</div>
      </div>
      {error ? <div className="badge badge-danger">{error}</div> : null}
      <div className="app-card" style={{ padding: 0 }}>
        {rows.map((row) => (
          <div key={row.id} style={{ padding: 14, borderBottom: "1px solid var(--line)", display: "flex", justifyContent: "space-between", gap: 12 }}>
            <div>
              <strong>{row.name}</strong>
              <div style={{ color: "var(--muted)", fontSize: 12 }}>{row.resource_type} · {new Date(row.updated_at).toLocaleString()}</div>
            </div>
            <button className="btn-ghost" type="button" onClick={() => restore(row.id)}>Restore</button>
          </div>
        ))}
        {!rows.length ? <div className="empty-state"><div className="empty-state-title">Trash is empty.</div></div> : null}
      </div>
    </div>
  );
}
