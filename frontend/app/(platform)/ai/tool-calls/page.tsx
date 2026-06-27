"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { aiApi, type AiRun, type AiRunDetail } from "@/lib/api/endpoints/ai";
import { ApiError } from "@/lib/api";

export default function AiToolCallsPage() {
  const [runs, setRuns] = useState<AiRun[]>([]);
  const [expanded, setExpanded] = useState<AiRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRuns(await aiApi.listRuns({ limit: 100 }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load AI runs.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggle(run: AiRun) {
    if (expanded?.id === run.id) {
      setExpanded(null);
      return;
    }
    try {
      setExpanded(await aiApi.runDetail(run.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load run detail.");
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Tool calls" type="AI" status={`${runs.length} runs`} />
      {loading ? <LoadingState label="Loading AI runs..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && !error ? (
        runs.length ? (
          <section className="app-card overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                <tr>
                  <th className="px-4 py-3">When</th>
                  <th className="px-4 py-3">Provider / Model</th>
                  <th className="px-4 py-3">Template</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <Fragment key={run.id}>
                    <tr className="border-t border-[var(--line-soft)]">
                      <td className="px-4 py-3 text-xs text-[var(--muted)]">{new Date(run.created_at).toLocaleString()}</td>
                      <td className="px-4 py-3 text-xs">{run.provider || "—"} / {run.model || "—"}</td>
                      <td className="px-4 py-3 font-mono text-xs">{run.prompt_template || "—"}</td>
                      <td className="px-4 py-3 text-xs">{run.status}</td>
                      <td className="px-4 py-3 text-right">
                        <button type="button" className="toolbar-button" onClick={() => void toggle(run)}>
                          {expanded?.id === run.id ? "Hide" : "Tool calls"}
                        </button>
                      </td>
                    </tr>
                    {expanded?.id === run.id ? (
                      <tr className="border-t border-[var(--line-soft)] bg-[var(--panel-2)]">
                        <td colSpan={5} className="px-4 py-3">
                          {expanded.tool_calls.length ? (
                            <div className="space-y-2">
                              {expanded.tool_calls.map((tc) => (
                                <div key={tc.id} className="rounded border border-[var(--line-soft)] p-3 text-xs">
                                  <div className="font-mono font-medium">{tc.tool_name} · {tc.status}</div>
                                  <pre className="mt-1 overflow-x-auto text-[var(--muted)]">{JSON.stringify(tc.output_summary ?? tc.input ?? {}, null, 2)}</pre>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-xs text-[var(--muted)]">No tool calls recorded for this run.</p>
                          )}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </section>
        ) : (
          <EmptyState title="No AI runs yet" detail="AI SQL drafts and runs will appear here." />
        )
      ) : null}
    </div>
  );
}
