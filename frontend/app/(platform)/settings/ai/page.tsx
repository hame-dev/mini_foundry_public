"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import {
  getAISettings,
  providerLabel,
  saveAISettings,
  type AIProviderInfo,
  type AIProviderName,
} from "@/lib/aiSettings";
import { ResourceHeader } from "@/components/foundry/FoundryPrimitives";
import type { AISettings } from "@/lib/types";

const FALLBACK_PROVIDERS: AIProviderInfo[] = [
  { name: "ollama", label: "Ollama (local)", default_model: "qwen3.5:4b", configured: true, local: true },
  { name: "gemini", label: "Gemini", default_model: "gemini-1.5-pro", configured: false, local: false },
  { name: "openai_compatible", label: "OpenAI compatible", default_model: "", configured: false, local: false },
];

export default function AISettingsPage() {
  const [providers, setProviders] = useState<AIProviderInfo[]>(FALLBACK_PROVIDERS);
  const [provider, setProvider] = useState<AIProviderName>("ollama");
  const [model, setModel] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [policy, setPolicy] = useState("metadata_only");
  const [serverConfigured, setServerConfigured] = useState(false);
  const [saved, setSaved] = useState(false);
  const selected = useMemo(() => providers.find((p) => p.name === provider), [providers, provider]);

  useEffect(() => {
    const current = getAISettings();
    setProvider(current.provider);
    setModel(current.model);
    Promise.all([
      apiFetch<AIProviderInfo[]>("/ai/providers"),
      apiFetch<AISettings>("/settings/ai").catch(() => null),
    ])
      .then(([rows, persisted]) => {
        setProviders(rows);
        const providerName = (persisted?.provider as AIProviderName | undefined) ?? current.provider;
        setProvider(providerName);
        setModel(persisted?.model ?? current.model);
        setApiBase(persisted?.api_base ?? "");
        setPolicy(persisted?.policy ?? "metadata_only");
        setServerConfigured(Boolean(persisted?.api_key_configured));
        const found = rows.find((p) => p.name === providerName);
        if (!persisted?.model && !current.model && found?.default_model) setModel(found.default_model);
      })
      .catch(() => undefined);
  }, []);

  function chooseProvider(value: AIProviderName) {
    setProvider(value);
    const next = providers.find((p) => p.name === value);
    setModel(next?.default_model ?? "");
  }

  async function save() {
    const persisted = await apiFetch<AISettings>("/settings/ai", {
      method: "PUT",
      body: JSON.stringify({
        provider,
        model: model.trim(),
        api_base: apiBase.trim() || null,
        api_key: apiKey.trim() || null,
        policy,
        extra: {},
      }),
    });
    saveAISettings({ provider: persisted.provider as AIProviderName, model: persisted.model ?? "" });
    setServerConfigured(persisted.api_key_configured);
    setApiKey("");
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1600);
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <ResourceHeader
        eyebrow="Mini Foundry Settings"
        title="AI Provider"
        subtitle="Persist the default provider and model used by SQL, dashboard generation, and pipeline generation."
        tabs={[{ label: "Provider", id: "Provider" }, { label: "Environment", id: "Environment" }, { label: "Policy", id: "Policy" }]}
        activeTab="Provider"
      />

      <section className="app-card p-4 space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="block text-xs font-semibold mb-1">Default provider</label>
            <select className="input-dark" value={provider} onChange={(e) => chooseProvider(e.target.value as AIProviderName)}>
              {providers.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.label}{p.configured ? "" : " (needs env)"}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">Default model</label>
            <input
              className="input-dark"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={selected?.default_model || "model name"}
            />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">API base URL</label>
            <input className="input-dark" value={apiBase} onChange={(e) => setApiBase(e.target.value)} placeholder="http://localhost:11434 or provider base URL" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">API key</label>
            <input className="input-dark" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={serverConfigured ? "Configured on server" : "Optional backend-stored key"} />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1">AI data policy</label>
            <select className="input-dark" value={policy} onChange={(e) => setPolicy(e.target.value)}>
              <option value="local_only">Local only</option>
              <option value="metadata_only">Metadata only</option>
              <option value="cloud_allowed">Cloud allowed</option>
            </select>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-primary" onClick={save}>Save AI settings</button>
          {saved && <span className="badge badge-success">Saved</span>}
        </div>
      </section>

      <section className="app-card">
        <div className="section-header">
          <span className="section-header-title">Provider Status</span>
        </div>
        <div className="divide-y" style={{ borderColor: "var(--line)" }}>
          {providers.map((p) => (
            <div key={p.name} className="grid gap-2 p-4 md:grid-cols-[180px_1fr_120px]">
              <div className="font-semibold">{providerLabel(p.name)}</div>
              <div className="font-mono text-xs" style={{ color: "var(--text-2)" }}>
                Default model: {p.default_model || "not set"}
              </div>
              <span className={`badge ${p.configured ? "badge-success" : "badge-warning"}`}>
                {p.configured ? "Configured" : "Needs env"}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="app-card p-4 space-y-2">
        <h2 className="text-sm font-semibold">Server environment keys</h2>
        <p className="text-xs" style={{ color: "var(--muted)" }}>
          API keys stay on the backend. Configure them in `.env` or Compose: `GEMINI_API_KEY`,
          `CUSTOM_AI_BASE_URL`, `CUSTOM_AI_KEY`, `OLLAMA_BASE_URL`, and matching default model variables.
        </p>
      </section>
    </div>
  );
}
