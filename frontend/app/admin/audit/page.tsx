"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { AuditLog } from "@/lib/types";

export default function AuditPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<AuditLog[]>("/admin/audit").then(setLogs).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="text-red-600">{error}</div>;

  return (
    <div className="space-y-3">
      <h1 className="text-2xl font-semibold">Audit log</h1>
      <div className="app-card overflow-hidden">
      <table className="data-table">
        <thead>
          <tr>
            <th className="px-3 py-2">Time</th>
            <th className="px-3 py-2">Event</th>
            <th className="px-3 py-2">User</th>
            <th className="px-3 py-2">Resource</th>
            <th className="px-3 py-2">Provider</th>
            <th className="px-3 py-2">Input</th>
            <th className="px-3 py-2">Output</th>
          </tr>
        </thead>
        <tbody>
          {logs.map((l) => (
            <tr key={l.id} className="border-t align-top">
              <td className="px-3 py-1">{new Date(l.created_at).toLocaleString()}</td>
              <td className="px-3 py-1 font-mono">{l.event_type}</td>
              <td className="px-3 py-1 font-mono">{l.user_id?.slice(0, 8) ?? "—"}</td>
              <td className="px-3 py-1 font-mono">{l.resource_type}:{l.resource_id?.slice(0, 8)}</td>
              <td className="px-3 py-1">{l.provider ?? "—"}</td>
              <td className="px-3 py-1 font-mono text-gray-500 max-w-xs truncate">
                {l.input_summary ? JSON.stringify(l.input_summary) : "—"}
              </td>
              <td className="px-3 py-1 font-mono text-gray-500 max-w-xs truncate">
                {l.output_summary ? JSON.stringify(l.output_summary) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
