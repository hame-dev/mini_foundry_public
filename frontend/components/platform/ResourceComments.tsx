"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Comment = {
  id: string;
  resource_id: string;
  parent_comment_id: string | null;
  author_id: string | null;
  author_email?: string | null;
  body: string;
  mentions: string[];
  status: string;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
};

export function ResourceComments({ resourceId }: { resourceId?: string | null }) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!resourceId) return;
    setLoading(true);
    try {
      setComments(await apiFetch<Comment[]>(`/collaboration/resources/${resourceId}/comments`));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load comments.");
    } finally {
      setLoading(false);
    }
  }, [resourceId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!resourceId || !body.trim()) return;
    setSaving(true);
    try {
      await apiFetch(`/collaboration/resources/${resourceId}/comments`, {
        method: "POST",
        body: JSON.stringify({ body: body.trim() }),
      });
      setBody("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to add comment.");
    } finally {
      setSaving(false);
    }
  }

  async function resolve(commentId: string) {
    try {
      await apiFetch(`/collaboration/comments/${commentId}/resolve`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to resolve comment.");
    }
  }

  if (!resourceId) return null;

  return (
    <section className="app-card p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">Comments</h2>
          <p className="text-xs text-[var(--muted)]">Mentions like @user@example.com notify collaborators.</p>
        </div>
        <span className="badge">{comments.filter((comment) => comment.status !== "resolved").length} open</span>
      </div>
      {error ? <div className="mb-3 rounded border border-[var(--danger)] p-2 text-sm text-[var(--danger)]">{error}</div> : null}
      <form className="mb-4 grid gap-2" onSubmit={submit}>
        <textarea className="input-dark min-h-24 w-full" value={body} onChange={(event) => setBody(event.target.value)} placeholder="Add a comment or mention a collaborator" />
        <button type="submit" className="toolbar-button justify-self-end" disabled={saving || !body.trim()}>{saving ? "Posting" : "Post comment"}</button>
      </form>
      <div className="grid gap-2">
        {loading ? (
          <div className="empty-state"><div className="empty-state-title">Loading comments…</div></div>
        ) : comments.length ? comments.map((comment) => (
          <article key={comment.id} className="rounded border border-[var(--line-soft)] p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-[var(--text-2)]">
                {comment.author_email ?? (comment.author_id ? comment.author_id.slice(0, 8) : "Unknown author")}
              </span>
              <span className="font-mono text-xs text-[var(--muted)]">{new Date(comment.created_at).toLocaleString()}</span>
            </div>
            <div className="mb-2 flex justify-end"><span className="badge">{comment.status}</span></div>
            <p className="whitespace-pre-wrap text-sm">{comment.body}</p>
            {comment.status !== "resolved" ? (
              <button type="button" className="toolbar-button mt-3" onClick={() => void resolve(comment.id)}>Resolve</button>
            ) : null}
          </article>
        )) : <div className="empty-state"><div className="empty-state-title">No comments</div></div>}
      </div>
    </section>
  );
}
