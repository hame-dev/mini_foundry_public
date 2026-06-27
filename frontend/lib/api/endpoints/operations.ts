import { apiFetch } from "@/lib/api";

export type Job = {
  id: string;
  user_id: string | null;
  job_type: string;
  status: string;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
  progress: Record<string, unknown> | null;
  resource_type: string | null;
  resource_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type JobAttempt = {
  id: string;
  attempt_number: number;
  celery_task_id: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  created_at: string;
};

export type JobLogEvent = {
  id: string;
  attempt_id: string | null;
  level: string;
  message: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};

export type JobDetail = Job & {
  attempts: JobAttempt[];
  log_events: JobLogEvent[];
};

export type Worker = {
  name: string;
  status: string;
  active_task_count: number;
  pool: string | null;
};

export type Workers = { configured: boolean; workers: Worker[] };

export type Queues = { queues: { name: string; depth: number }[] };

export type Caches = {
  used_memory: number | null;
  used_memory_human: string | null;
  total_keys: number | null;
  namespaces: { prefix: string; key_count: number }[];
};

export type Storage = {
  backend: string;
  location: string;
  reachable: boolean;
  object_count: number | null;
  total_bytes: number | null;
  detail: string | null;
};

export type Metrics = {
  window_hours: number;
  total_events: number;
  error_events: number;
  event_counts: { event_type: string; count: number }[];
  latency: { resource_type: string; count: number; avg_ms: number; max_ms: number }[];
};

export type LogEntry = {
  id: string;
  user_id: string | null;
  event_type: string;
  resource_type: string | null;
  resource_id: string | null;
  provider: string | null;
  input_summary: Record<string, unknown> | null;
  output_summary: Record<string, unknown> | null;
  created_at: string;
};

export type LogFilters = {
  event_type?: string;
  resource_type?: string;
  since?: string;
  limit?: number;
};

export type Hardening = {
  environment: string;
  enforced: boolean;
  status: string;
  issues: string[];
  bearer_auth_enabled: boolean;
  backup_restore_verified: boolean;
  metrics_alerting_configured: boolean;
  rootless_sandbox_host: boolean;
};

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const operationsApi = {
  health() {
    return apiFetch<{ status: string; checks: Record<string, { status: string; detail?: string }> }>("/system/health");
  },
  jobs() {
    return apiFetch<Job[]>("/jobs");
  },
  jobDetail(id: string) {
    return apiFetch<JobDetail>(`/jobs/${id}`);
  },
  cancelJob(id: string) {
    return apiFetch<Job>(`/jobs/${id}/cancel`, { method: "POST" });
  },
  retryJob(id: string) {
    return apiFetch<Job>(`/jobs/${id}/retry`, { method: "POST" });
  },
  workers() {
    return apiFetch<Workers>("/operations/workers");
  },
  queues() {
    return apiFetch<Queues>("/operations/queues");
  },
  caches() {
    return apiFetch<Caches>("/operations/caches");
  },
  flushCache(prefix: string) {
    return apiFetch<{ prefix: string; deleted: number }>(`/operations/caches/flush${qs({ prefix })}`, { method: "POST" });
  },
  storage() {
    return apiFetch<Storage>("/operations/storage");
  },
  metrics(windowHours?: number) {
    return apiFetch<Metrics>(`/operations/metrics${qs({ window_hours: windowHours })}`);
  },
  logs(filters: LogFilters = {}) {
    return apiFetch<LogEntry[]>(`/operations/logs${qs(filters)}`);
  },
  hardening() {
    return apiFetch<Hardening>("/operations/hardening");
  },
};
