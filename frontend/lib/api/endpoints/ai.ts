import { apiFetch } from "@/lib/api";

export type AIProvider = { name: string; label: string; default_model: string; configured: boolean; local: boolean };

export type AiRun = {
  id: string;
  user_id: string | null;
  provider: string | null;
  model: string | null;
  policy: string;
  prompt_template: string | null;
  status: string;
  token_estimate: number | null;
  created_at: string;
};

export type AiToolCall = {
  id: string;
  ai_run_id: string | null;
  tool_name: string;
  input: Record<string, unknown> | null;
  output_summary: Record<string, unknown> | null;
  status: string;
  created_at: string;
};

export type AiRunDetail = AiRun & { tool_calls: AiToolCall[] };

export type AiUsage = {
  window_hours: number;
  total_runs: number;
  total_tokens: number;
  by_provider_model: { provider: string | null; model: string | null; run_count: number; token_total: number }[];
  credits: number;
  latency_ms_avg: number;
};

export type PromptTemplate = {
  id: string;
  name: string;
  description: string | null;
  template: string;
  version: number;
  created_at: string;
};

export type AiEvaluation = {
  id: string;
  name: string;
  description: string | null;
  prompt_template_id: string | null;
  provider: string | null;
  model: string | null;
  cases: Record<string, unknown> | null;
  score: number | null;
  results: Record<string, unknown> | null;
  status: string;
  created_at: string;
};

export type PromptPreview = {
  rendered_prompt: string;
  redacted_prompt: string;
  redactions: { type: string; count: number }[];
  permission_notices: string[];
};

export type SqlDraft = {
  sql: string;
  explanation: string;
  confidence: number | string;
  provider: string;
  model: string;
  dataset_ids: string[];
};

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const aiApi = {
  providers: () => apiFetch<AIProvider[]>("/ai/providers"),
  draftSql: (payload: { question: string; provider: string; model?: string | null; dataset_ids: string[] }) =>
    apiFetch<SqlDraft>("/ai/sql", { method: "POST", body: JSON.stringify(payload) }),
  runSql: (payload: { sql: string; dataset_ids: string[] }) =>
    apiFetch<any>("/ai/run-sql", { method: "POST", body: JSON.stringify(payload) }),
  listRuns: (filters: { provider?: string; status_filter?: string; limit?: number } = {}) =>
    apiFetch<AiRun[]>(`/ai/runs${qs(filters)}`),
  runDetail: (id: string) => apiFetch<AiRunDetail>(`/ai/runs/${id}`),
  listToolCalls: (limit?: number) => apiFetch<AiToolCall[]>(`/ai/tool-calls${qs({ limit })}`),
  usage: (windowHours?: number) => apiFetch<AiUsage>(`/ai/usage${qs({ window_hours: windowHours })}`),
  listPrompts: () => apiFetch<PromptTemplate[]>("/ai/prompts"),
  createPrompt: (payload: { name: string; description?: string | null; template: string }) =>
    apiFetch<PromptTemplate>("/ai/prompts", { method: "POST", body: JSON.stringify(payload) }),
  previewPrompt: (payload: { template?: string | null; prompt_template_id?: string | null; context?: Record<string, unknown>; dataset_ids?: string[] }) =>
    apiFetch<PromptPreview>("/ai/prompts/preview", { method: "POST", body: JSON.stringify(payload) }),
  deletePrompt: (id: string) => apiFetch<{ ok: boolean }>(`/ai/prompts/${id}`, { method: "DELETE" }),
  listEvaluations: () => apiFetch<AiEvaluation[]>("/ai/evaluations"),
  createEvaluation: (payload: {
    name: string;
    description?: string | null;
    provider?: string | null;
    model?: string | null;
    score?: number | null;
  }) => apiFetch<AiEvaluation>("/ai/evaluations", { method: "POST", body: JSON.stringify(payload) }),
  deleteEvaluation: (id: string) => apiFetch<{ ok: boolean }>(`/ai/evaluations/${id}`, { method: "DELETE" }),
  runEvaluation: (id: string) => apiFetch<AiEvaluation>(`/ai/evaluations/${id}/run`, { method: "POST" }),
  datasets: () => apiFetch<{ id: string; name: string }[]>("/data/datasets"),
};
