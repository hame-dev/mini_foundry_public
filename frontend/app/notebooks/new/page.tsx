"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { NotebookDetail } from "@/lib/notebooks";

const AI_POLICIES = ["local_only", "cloud_allowed", "metadata_only", "no_external"];

export default function NewNotebookPage() {
  const router = useRouter();
  const [title, setTitle] = useState("Untitled notebook");
  const [description, setDescription] = useState("");
  const [aiPolicy, setAiPolicy] = useState("local_only");
  const [kind, setKind] = useState<"sql" | "python">("python");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const nb = await apiFetch<NotebookDetail>("/notebooks", {
        method: "POST",
        body: JSON.stringify({ title, description: description || null, ai_policy: aiPolicy, notebook_kind: kind }),
      });
      router.push(`/notebooks/${nb.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  return (
    <div className="max-w-md space-y-4">
      <h1 className="text-2xl font-semibold">New notebook</h1>
      {error && <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded p-2">{error}</div>}
      <form onSubmit={create} className="app-card p-4 space-y-3">
        <div>
          <label className="block text-xs mb-1">Title</label>
          <input className="input-dark w-full"
            value={title} onChange={(e) => setTitle(e.target.value)} required />
        </div>
        <div>
          <label className="block text-xs mb-1">Description</label>
          <input className="input-dark w-full"
            value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs mb-1">Notebook type</label>
          <select className="input-dark w-full"
            value={kind} onChange={(e) => setKind(e.target.value as "sql" | "python")}>
            <option value="sql">SQL notebook</option>
            <option value="python">Python/Jupyter notebook</option>
          </select>
        </div>
        <div>
          <label className="block text-xs mb-1">AI policy</label>
          <select className="input-dark w-full"
            value={aiPolicy} onChange={(e) => setAiPolicy(e.target.value)}>
            {AI_POLICIES.map((p) => <option key={p}>{p}</option>)}
          </select>
        </div>
        <button disabled={busy}
          className="w-full btn-primary py-2 text-sm disabled:opacity-50">
          {busy ? "Creating..." : "Create"}
        </button>
      </form>
    </div>
  );
}
