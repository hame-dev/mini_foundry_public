"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { previewAction, triggerAction, type ActionPreview, type DashboardAction } from "@/lib/actions";
import { idempotencyKey } from "@/lib/idempotency";
import { useDashboardVariables } from "@/contexts/DashboardVariables";

type Props = {
  columns?: string[];
  rows?: Record<string, unknown>[];
  config: { columns?: string[]; page_size?: number; output_variable?: string };
  actions?: DashboardAction[];
  onFilterUpdate?: (filterId: string, value: unknown) => void;
};

export default function DataTable({ columns, rows, config, actions, onFilterUpdate }: Props) {
  const router = useRouter();
  const { setVariable } = useDashboardVariables();
  const [selectedRowIndex, setSelectedRowIndex] = useState<number | null>(null);
  const [pendingWorkflow, setPendingWorkflow] = useState<{
    actionName: string;
    row: Record<string, unknown>;
    preview: ActionPreview | null;
    loading: boolean;
    submitting: boolean;
    message: string | null;
    error: string | null;
  } | null>(null);
  const cols = config.columns?.length ? config.columns : columns || [];
  const data = rows || [];
  const rowAction = actions?.find((a) => a.event === "on_row_click");

  async function openWorkflowConfirmation(actionName: string, row: Record<string, unknown>) {
    setPendingWorkflow({ actionName, row, preview: null, loading: true, submitting: false, message: null, error: null });
    try {
      const preview = await previewAction(actionName, { row });
      setPendingWorkflow((current) => current?.actionName === actionName ? { ...current, preview, loading: false } : current);
    } catch (e: unknown) {
      setPendingWorkflow((current) => current?.actionName === actionName
        ? { ...current, loading: false, error: e instanceof Error ? e.message : String(e) }
        : current);
    }
  }

  async function confirmWorkflowAction() {
    if (!pendingWorkflow || !pendingWorkflow.preview) return;
    if (!pendingWorkflow.preview.allowed || !pendingWorkflow.preview.preconditions_ok) return;
    setPendingWorkflow({ ...pendingWorkflow, submitting: true, message: null, error: null });
    try {
      const out = await triggerAction(pendingWorkflow.actionName, { row: pendingWorkflow.row }, idempotencyKey("dashboard_action"));
      const message = out.status === "pending_approval"
        ? `Approval requested: ${out.approval_request_id}`
        : out.status === "queued"
          ? `Queued: ${out.job_id}`
          : `Completed: ${out.status}`;
      setPendingWorkflow((current) => current ? { ...current, submitting: false, message } : current);
    } catch (e: unknown) {
      setPendingWorkflow((current) => current
        ? { ...current, submitting: false, error: e instanceof Error ? e.message : String(e) }
        : current);
    }
  }

  function handleRowClick(r: Record<string, unknown>, i: number) {
    setSelectedRowIndex(i);
    // Propagate to object-set variable if configured
    if (config.output_variable) {
      setVariable(config.output_variable, r);
    }
    if (!rowAction) return;
    if (rowAction.type === "open_object") {
      const id = r[rowAction.id_field];
      if (id !== undefined && id !== null) {
        router.push(`/objects/${rowAction.object_type}/${encodeURIComponent(String(id))}`);
      }
    } else if (rowAction.type === "filter" && onFilterUpdate) {
      const src = rowAction.source_field ?? rowAction.filter_id;
      onFilterUpdate(rowAction.filter_id, r[src]);
    } else if (rowAction.type === "navigate") {
      const to = rowAction.to;
      if (to.startsWith("http")) window.open(to, "_blank");
      else router.push(to);
    } else if (rowAction.type === "run_workflow") {
      void openWorkflowConfirmation(rowAction.action_name, r);
    }
  }

  return (
    <div className="h-full overflow-auto">
      <table className="w-full text-xs">
        <thead className="bg-gray-50 sticky top-0">
          <tr>{cols.map((c) => <th key={c} className="px-3 py-2 text-left">{c}</th>)}</tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i}
              onClick={() => handleRowClick(r, i)}
              className={`border-t transition-colors ${
                selectedRowIndex === i ? "bg-blue-100" :
                (rowAction || config.output_variable) ? "cursor-pointer hover:bg-blue-50" : ""
              }`}>
              {cols.map((c) => <td key={c} className="px-3 py-1 font-mono">{String(r[c] ?? "")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {pendingWorkflow && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-4" onClick={() => setPendingWorkflow(null)}>
          <div
            className="w-full max-w-md rounded border shadow-xl"
            style={{ background: "var(--panel)", borderColor: "var(--line)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-4 py-3 border-b flex items-start justify-between gap-3" style={{ borderColor: "var(--line)" }}>
              <div>
                <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>{pendingWorkflow.actionName}</h3>
                <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>Review dashboard row action before execution.</p>
              </div>
              <button className="btn-ghost text-xs" onClick={() => setPendingWorkflow(null)}>Close</button>
            </div>
            <div className="p-4 space-y-3">
              {pendingWorkflow.error ? (
                <div className="text-xs rounded border px-3 py-2" style={{ color: "var(--danger)", borderColor: "var(--danger-soft)" }}>
                  {pendingWorkflow.error}
                </div>
              ) : null}
              {pendingWorkflow.message ? (
                <div className="text-xs rounded border px-3 py-2" style={{ color: "var(--success)", borderColor: "var(--success-soft)" }}>
                  {pendingWorkflow.message}
                </div>
              ) : null}
              <div className="rounded border p-3 space-y-2" style={{ borderColor: "var(--line)", background: "var(--panel-2)" }}>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold" style={{ color: "var(--text)" }}>Side effects</span>
                  <span className="text-[11px]" style={{ color: "var(--muted)" }}>
                    {pendingWorkflow.loading ? "Checking..." : pendingWorkflow.preview?.approval_required ? "Approval required" : "Ready"}
                  </span>
                </div>
                {pendingWorkflow.preview?.missing_preconditions?.length ? (
                  <ul className="text-xs space-y-1" style={{ color: "var(--danger)" }}>
                    {pendingWorkflow.preview.missing_preconditions.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                ) : null}
                {(pendingWorkflow.preview?.side_effects || []).map((effect, idx) => (
                  <div key={idx} className="text-xs font-mono rounded px-2 py-1" style={{ color: "var(--text-2)", background: "var(--panel)" }}>
                    {String(effect.type || "effect")} · {String(effect.object_type || effect.workflow_key || "target")}
                  </div>
                ))}
              </div>
            </div>
            <div className="px-4 py-3 border-t flex justify-end gap-2" style={{ borderColor: "var(--line)" }}>
              <button className="btn-ghost text-xs" onClick={() => setPendingWorkflow(null)}>Cancel</button>
              <button
                className="btn-primary text-xs"
                disabled={
                  pendingWorkflow.loading
                  || pendingWorkflow.submitting
                  || !pendingWorkflow.preview
                  || !pendingWorkflow.preview.allowed
                  || !pendingWorkflow.preview.preconditions_ok
                }
                onClick={confirmWorkflowAction}
              >
                {pendingWorkflow.submitting ? "Running..." : pendingWorkflow.preview?.approval_required ? "Request approval" : "Run action"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
