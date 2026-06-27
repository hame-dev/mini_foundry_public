"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { getAISettings, providerLabel } from "@/lib/aiSettings";
import type { PipelineEdge, PipelineNode } from "@/lib/pipelines";

export function AiPipelinePrompt({
  onGenerated,
  onClose,
}: {
  onGenerated: (name: string, description: string | null, nodes: PipelineNode[], edges: PipelineEdge[]) => void;
  onClose: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function go() {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<{
        name: string;
        description: string | null;
        nodes: PipelineNode[];
        edges: PipelineEdge[];
      }>("/pipelines/ai-generate", {
        method: "POST",
        body: JSON.stringify({ prompt, provider, model: model.trim() || null }),
      });
      onGenerated(res.name, res.description, res.nodes, res.edges);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "AI generation failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const ai = getAISettings();
    setProvider(ai.provider);
    setModel(ai.model);
  }, []);

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: "rgba(10,13,18,0.65)",
        backdropFilter: "blur(2px)",
        display: "grid",
        placeItems: "center",
        zIndex: 50,
      }}
    >
      <div
        className="app-card"
        style={{
          width: "100%",
          maxWidth: 520,
          padding: 20,
          display: "grid",
          gap: 12,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--muted-2)",
            }}
          >
            AI
          </div>
          <h2 style={{ margin: 0, fontSize: 16 }}>Generate pipeline from prompt</h2>
        </div>
        <textarea
          rows={5}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Describe the pipeline you want, referencing dataset names from the catalog."
          style={{ padding: 10, fontSize: 12.5, lineHeight: 1.5 }}
        />
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            style={{ padding: "6px 8px", fontSize: 12 }}
          >
            {(["ollama", "gemini", "openai_compatible"] as const).map((p) => (
              <option key={p} value={p}>{providerLabel(p)}</option>
            ))}
          </select>
          <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="Model" style={{ padding: "6px 8px", fontSize: 12, minWidth: 150 }} />
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="button" className="btn-primary" onClick={go} disabled={loading || !prompt.trim()}>
              {loading ? "Generating…" : "Generate"}
            </button>
          </div>
        </div>
        {error ? (
          <div
            style={{
              padding: "8px 10px",
              border: "1px solid rgba(255,111,125,0.35)",
              background: "var(--danger-soft)",
              color: "var(--danger)",
              borderRadius: 3,
              fontSize: 12,
            }}
          >
            {error}
          </div>
        ) : null}
      </div>
    </div>
  );
}
