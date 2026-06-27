"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Notification = {
  id: string;
  topic: string;
  title: string;
  body: string | null;
  resource_type: string | null;
  resource_id: string | null;
  read_at: string | null;
  created_at: string;
};

export default function NotificationsPage() {
  const [rows, setRows] = useState<Notification[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setRows(await apiFetch<Notification[]>("/notifications"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function markAllRead() {
    await apiFetch("/notifications/read-all", { method: "POST" });
    await load();
  }

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="app-card" style={{ padding: 16, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div className="panel-heading" style={{ border: 0, padding: 0 }}>Notifications</div>
          <div style={{ color: "var(--muted)", fontSize: 13 }}>Operational events, approvals, exports, and automation alerts.</div>
        </div>
        <button className="btn-ghost" type="button" onClick={markAllRead}>Mark all read</button>
      </div>
      {error ? <div className="badge badge-danger">{error}</div> : null}
      <div className="app-card" style={{ padding: 0 }}>
        {rows.map((row) => (
          <div key={row.id} style={{ padding: 14, borderBottom: "1px solid var(--line)", display: "grid", gap: 4 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <strong>{row.title}</strong>
              <span className={row.read_at ? "badge" : "badge badge-success"}>{row.read_at ? "Read" : "Unread"}</span>
            </div>
            {row.body ? <div style={{ color: "var(--muted)" }}>{row.body}</div> : null}
            <div style={{ color: "var(--muted)", fontSize: 12 }}>
              {row.topic} · {new Date(row.created_at).toLocaleString()}
            </div>
          </div>
        ))}
        {!rows.length ? <div className="empty-state"><div className="empty-state-title">No notifications.</div></div> : null}
      </div>
    </div>
  );
}
