"use client";

import type { PreviewOut } from "@/lib/pipelines";

export function PreviewPanel({
  preview,
  error,
  loading,
  onRun,
  onClose,
}: {
  preview: PreviewOut | null;
  error: string | null;
  loading: boolean;
  onRun: () => void;
  onClose: () => void;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateRows: "auto 1fr",
        minHeight: 0,
        borderTop: "1px solid var(--line)",
        background: "var(--bg-2)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 14px",
          borderBottom: "1px solid var(--line-soft)",
          background: "var(--panel-2)",
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--muted-2)",
          }}
        >
          Preview
        </span>
        {preview ? (
          <span className="badge">
            {preview.rows.length} rows · {preview.columns.length} cols
          </span>
        ) : null}
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button type="button" className="btn-ghost" onClick={onRun} disabled={loading}>
            {loading ? "Running…" : "Re-run preview"}
          </button>
          <button type="button" className="btn-ghost" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
      <div style={{ minHeight: 0, overflow: "auto", padding: 0 }}>
        {error ? (
          <div
            style={{
              margin: 14,
              padding: "10px 12px",
              border: "1px solid rgba(255,111,125,0.35)",
              background: "var(--danger-soft)",
              color: "var(--danger)",
              borderRadius: 3,
              fontSize: 12,
            }}
          >
            {error}
          </div>
        ) : preview ? (
          <table className="w-full text-xs">
            <thead>
              <tr>
                {preview.columns.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((r, i) => (
                <tr key={i}>
                  {preview.columns.map((c) => (
                    <td key={c} className="font-mono" style={{ fontSize: 11.5 }}>
                      {String(r[c] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty-state">
            <div className="empty-state-title">No preview yet</div>
            <div className="empty-state-help">Hit Preview to compile the graph and fetch sample rows.</div>
          </div>
        )}
      </div>
    </div>
  );
}
