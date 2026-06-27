"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { getAISettings, providerLabel } from "@/lib/aiSettings";
import type { DashboardLayout } from "@/lib/dashboards";

type Props = {
  onResult: (result: { title: string; description: string | null; layout: DashboardLayout }) => void;
};

const PROVIDERS = ["ollama", "gemini", "openai_compatible"];

export default function AiDashboardPrompt({ onResult }: Props) {
  const [prompt, setPrompt] = useState("Give me a sales summary with revenue by month and order counts by status");
  const [provider, setProvider] = useState("ollama");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<{ title: string; description: string | null; layout: DashboardLayout }>(
        "/dashboards/ai-generate",
        { method: "POST", body: JSON.stringify({ prompt, provider, model: model.trim() || null }) },
      );
      onResult(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const ai = getAISettings();
    setProvider(ai.provider);
    setModel(ai.model);
  }, []);

  return (
    <div className="app-card p-4 space-y-3">
      <h2 className="font-semibold" style={{ color: "var(--text)" }}>Generate with AI</h2>
      <select className="input-dark" value={provider} onChange={(e) => setProvider(e.target.value)}>
        {PROVIDERS.map((p) => <option key={p} value={p}>{providerLabel(p)}</option>)}
      </select>
      <input className="input-dark" value={model} onChange={(e) => setModel(e.target.value)} placeholder="Model override" />
      <textarea className="input-dark" style={{ height: 96, resize: "vertical" }}
        value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      {error && <div className="text-xs" style={{ color: "var(--danger)" }}>{error}</div>}
      <button onClick={go} disabled={busy} className="w-full btn-primary disabled:opacity-50">
        {busy ? "Generating..." : "Generate"}
      </button>
    </div>
  );
}
