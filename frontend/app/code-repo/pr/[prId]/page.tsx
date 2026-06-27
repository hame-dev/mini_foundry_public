"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

type Comment = {
  id: string;
  body: string;
  author: string;
  file: string | null;
  line: number | null;
  created_at: string;
};

type PR = {
  id: string;
  repo_id: string;
  title: string;
  description: string | null;
  source_branch: string;
  target_branch: string;
  status: string;
  comments: Comment[];
  created_at: string;
  merged_at: string | null;
};

type DiffLine = {
  type: "add" | "remove" | "context" | "header";
  content: string;
  lineNo: number | null;
};

function parseDiff(raw: string): DiffLine[] {
  const lines: DiffLine[] = [];
  let lineNo = 0;
  for (const l of raw.split("\n")) {
    if (l.startsWith("@@")) {
      const m = l.match(/@@ [^+]*\+(\d+)/);
      lineNo = m ? parseInt(m[1], 10) - 1 : lineNo;
      lines.push({ type: "header", content: l, lineNo: null });
    } else if (l.startsWith("+")) {
      lineNo++;
      lines.push({ type: "add", content: l.slice(1), lineNo });
    } else if (l.startsWith("-")) {
      lines.push({ type: "remove", content: l.slice(1), lineNo: null });
    } else {
      lineNo++;
      lines.push({ type: "context", content: l.slice(1), lineNo });
    }
  }
  return lines;
}

export default function PRReviewPage({ params }: { params: Promise<{ prId: string }> }) {
  const { prId } = use(params);
  const router = useRouter();
  const [pr, setPr] = useState<PR | null>(null);
  const [diff, setDiff] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [commentBody, setCommentBody] = useState("");
  const [commentLine, setCommentLine] = useState<number | null>(null);
  const [commentFile, setCommentFile] = useState<string | null>(null);
  const [activeFile, setActiveFile] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<PR>(`/code-repo/pull-requests/${prId}`)
      .then(setPr)
      .catch((e) => setError(e.message));
    apiFetch<{ diff: string }>(`/code-repo/pull-requests/${prId}/diff`)
      .then((d) => setDiff(d.diff))
      .catch(() => {});
  }, [prId]);

  async function updateStatus(s: string) {
    setBusy(true);
    try {
      const updated = await apiFetch<PR>(`/code-repo/pull-requests/${prId}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status: s }),
      });
      setPr(updated);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitComment() {
    if (!commentBody.trim()) return;
    setBusy(true);
    try {
      const updated = await apiFetch<PR>(`/code-repo/pull-requests/${prId}/comments`, {
        method: "POST",
        body: JSON.stringify({ body: commentBody, file: commentFile, line: commentLine }),
      });
      setPr(updated);
      setCommentBody("");
      setCommentLine(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function handleLineClick(line: DiffLine, file: string | null) {
    if (line.type === "add" || line.type === "context") {
      setCommentLine(line.lineNo);
      setCommentFile(file);
    }
  }

  if (error && !pr) return <div className="p-4" style={{ color: "var(--danger)" }}>{error}</div>;
  if (!pr) return <div className="p-4" style={{ color: "var(--muted)" }}>Loading…</div>;

  const diffLines = parseDiff(diff);

  // Group diff lines by file (detect "diff --git" headers)
  const files: string[] = [];
  for (const l of diff.split("\n")) {
    if (l.startsWith("diff --git")) {
      const m = l.match(/b\/(.+)$/);
      if (m) files.push(m[1]);
    }
  }
  const currentFile = files[0] ?? null;

  const statusBadge: Record<string, string> = {
    open: "badge badge-accent",
    approved: "badge badge-success",
    merged: "badge",
    closed: "badge",
  };

  return (
    <div className="flex flex-col h-[calc(100vh-80px)]">
      {/* Header */}
      <header style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }} className="px-6 py-4 flex items-start justify-between">
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted-2)", marginBottom: 4 }}>Pull Request</div>
          <h1 style={{ color: "var(--text)" }} className="text-lg font-bold">{pr.title}</h1>
          <div className="flex items-center gap-3 mt-1 text-xs" style={{ color: "var(--muted)" }}>
            <span className={statusBadge[pr.status] ?? "badge"}>{pr.status.toUpperCase()}</span>
            <span><strong style={{ color: "var(--text)" }}>{pr.source_branch}</strong> → <strong style={{ color: "var(--text)" }}>{pr.target_branch}</strong></span>
            <span>{new Date(pr.created_at).toLocaleDateString()}</span>
          </div>
          {pr.description && <p className="mt-2 text-sm" style={{ color: "var(--text-2)" }}>{pr.description}</p>}
        </div>
        {pr.status === "open" && (
          <div className="flex gap-2">
            <button onClick={() => updateStatus("approved")} disabled={busy} className="btn-ghost text-sm disabled:opacity-50" style={{ color: "var(--success)" }}>
              Approve
            </button>
            <button onClick={() => updateStatus("merged")} disabled={busy} className="btn-primary text-sm disabled:opacity-50">
              Merge
            </button>
            <button onClick={() => updateStatus("closed")} disabled={busy} className="btn-ghost text-sm disabled:opacity-50">
              Close
            </button>
          </div>
        )}
      </header>

      <div className="flex flex-1 min-h-0">
        {/* Diff viewer */}
        <main style={{ background: "var(--bg-2)" }} className="flex-1 min-w-0 overflow-auto font-mono text-xs">
          {diff ? (
            <table className="w-full border-collapse">
              <tbody>
                {diffLines.map((line, i) => {
                  const rowClass =
                    line.type === "add"
                      ? "diff-add"
                      : line.type === "remove"
                      ? "diff-remove"
                      : line.type === "header"
                      ? "diff-header"
                      : "";
                  const prefix =
                    line.type === "add" ? "+" : line.type === "remove" ? "-" : " ";

                  return (
                    <tr
                      key={i}
                      className={`${rowClass} ${line.type === "add" || line.type === "context" ? "cursor-pointer hover:opacity-90" : ""}`}
                      onClick={() => handleLineClick(line, currentFile)}
                    >
                      <td className="select-none text-right px-2 w-10" style={{ color: "var(--muted-2)", borderRight: "1px solid var(--line)" }}>
                        {line.lineNo ?? ""}
                      </td>
                      <td className="select-none px-1 w-4">{prefix}</td>
                      <td className="px-3 py-0.5 whitespace-pre">{line.content}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div style={{ color: "var(--muted-2)" }} className="text-center py-12">No diff available.</div>
          )}
        </main>

        {/* Comment panel */}
        <aside style={{ width: 320, borderLeft: "1px solid var(--line)", background: "var(--panel)" }} className="shrink-0 flex flex-col">
          <div className="section-header">
            <span className="section-header-title">Comments ({pr.comments.length})</span>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {pr.comments.length === 0 && (
              <p className="text-xs text-center py-4" style={{ color: "var(--muted-2)" }}>No comments yet.</p>
            )}
            {pr.comments.map((c) => (
              <div key={c.id} className="app-card p-2 text-xs space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-semibold" style={{ color: "var(--text)" }}>{c.author}</span>
                  <span style={{ color: "var(--muted-2)" }}>{new Date(c.created_at).toLocaleDateString()}</span>
                </div>
                {(c.file || c.line) && (
                  <div className="font-mono" style={{ fontSize: 10, color: "var(--accent)" }}>
                    {c.file && <span>{c.file}</span>}
                    {c.line && <span>:{c.line}</span>}
                  </div>
                )}
                <p style={{ color: "var(--text-2)" }} className="whitespace-pre-wrap">{c.body}</p>
              </div>
            ))}
          </div>

          {pr.status === "open" && (
            <div style={{ borderTop: "1px solid var(--line)" }} className="p-3 space-y-2">
              {commentLine && (
                <div className="font-mono" style={{ fontSize: 10, color: "var(--accent)" }}>
                  Commenting on line {commentLine}
                  {commentFile && ` of ${commentFile}`}
                  <button style={{ color: "var(--muted-2)" }} className="ml-2 hover:opacity-80" onClick={() => setCommentLine(null)}>×</button>
                </div>
              )}
              <textarea
                value={commentBody}
                onChange={(e) => setCommentBody(e.target.value)}
                placeholder="Leave a comment…"
                rows={3}
                className="input-dark resize-none"
                style={{ fontSize: 12 }}
              />
              <button
                onClick={submitComment}
                disabled={busy || !commentBody.trim()}
                className="w-full btn-primary text-xs py-1.5 disabled:opacity-50"
              >
                {busy ? "Submitting…" : "Add comment"}
              </button>
              {error && <p style={{ fontSize: 10, color: "var(--danger)" }}>{error}</p>}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
