"use client";

export type AIProviderName = "ollama" | "gemini" | "openai_compatible";

export type AIProviderInfo = {
  name: AIProviderName;
  label: string;
  default_model: string;
  configured: boolean;
  local: boolean;
};

export type AISettings = {
  provider: AIProviderName;
  model: string;
};

const KEY = "mf_ai_settings";
const DEFAULTS: AISettings = { provider: "ollama", model: "" };

export function getAISettings(): AISettings {
  if (typeof window === "undefined") return DEFAULTS;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return DEFAULTS;
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return DEFAULTS;
  }
}

export function saveAISettings(settings: AISettings) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, JSON.stringify(settings));
  window.dispatchEvent(new CustomEvent("mf-ai-settings-changed", { detail: settings }));
}

export function providerLabel(name: string) {
  if (name === "ollama") return "Ollama (local)";
  if (name === "gemini") return "Gemini";
  if (name === "openai_compatible") return "OpenAI compatible";
  return name;
}
