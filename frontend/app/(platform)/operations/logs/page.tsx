"use client";

import { useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { Button, Input } from "@/components/foundry";
import { operationsApi, type LogEntry } from "@/lib/api/endpoints/operations";
import { ApiError } from "@/lib/api";

export default function OperationsLogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [eventType, setEventType] = useState("");
  const [resourceType, setResourceType] = useState("");

  const load = useCallback(async (filters: { event_type?: string; resource_type?: string }) => {
    setLoading(true);
    setError(null);
    try {
      setLogs(await operationsApi.logs({ ...filters, limit: 200 }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load logs.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load({});
  }, [load]);

  function applyFilters() {
    void load({ event_type: eventType || undefined, resource_type: resourceType || undefined });
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Logs" type="Operations" status={`${logs.length} events`} />

      <section className="app-card flex flex-wrap items-end gap-3 p-4">
        <label className="flex flex-col gap-1 text-xs text-[var(--muted)]">
          Event type
          <Input value={eventType} onChange={(e) => setEventType(e.target.value)} placeholder="e.g. SQL_RUN" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--muted)]">
          Resource type
          <Input value={resourceType} onChange={(e) => setResourceType(e.target.value)} placeholder="e.g. dataset" />
        </label>
        <Button size="sm" onClick={applyFilters}>
          Apply
        </Button>
      </section>

      {loading ? <LoadingState label="Querying audit logs..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && !error ? (
        logs.length ? (
          <section className="app-card overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-[var(--muted)]">
                <tr>
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3">Event</th>
                  <th className="px-4 py-3">Resource</th>
                  <th className="px-4 py-3">User</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((l) => (
                  <tr key={l.id} className="border-t border-[var(--border)]">
                    <td className="px-4 py-2 whitespace-nowrap text-xs text-[var(--muted)]">
                      {new Date(l.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">{l.event_type}</td>
                    <td className="px-4 py-2 text-xs">
                      {l.resource_type ? `${l.resource_type}${l.resource_id ? ` · ${l.resource_id.slice(0, 8)}` : ""}` : "—"}
                    </td>
                    <td className="px-4 py-2 text-xs text-[var(--muted)]">{l.user_id ? l.user_id.slice(0, 8) : "system"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : (
          <EmptyState title="No matching log events" detail="Try widening the filters." />
        )
      ) : null}
    </div>
  );
}
