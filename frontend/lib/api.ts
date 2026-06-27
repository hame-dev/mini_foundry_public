export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api/v1";

export function getToken(): string | null {
  return null;
}

export function setToken(token: string | null) {
  void token;
}

function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const value = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`))
    ?.split("=")[1];
  return value ? decodeURIComponent(value) : null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("X-Request-ID")) {
    const id = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    headers.set("X-Request-ID", id);
  }
  if (!(init.body instanceof FormData) && init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const method = (init.method || "GET").toUpperCase();
  const csrf = getCookie("mf_csrf");
  if (csrf && !["GET", "HEAD", "OPTIONS"].includes(method) && !headers.has("X-CSRF-Token")) {
    headers.set("X-CSRF-Token", csrf);
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {}
    if (res.status === 401 && typeof window !== "undefined") {
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --- Quiver / time-series ---------------------------------------------------

export type TimeSeriesAnalysis = {
  dataset_id: string;
  dataset_name: string;
  time: string[];
  raw: number[];
  n: number;
  resample_freq: string | null;
  rolling?: { window: number; values: number[] };
  regression?: { slope: number; intercept: number; r2: number; line: number[] };
  fft?: { freq: number[]; amplitude: number[]; period: number[] };
};

export function analyzeTimeSeries(body: {
  dataset_id: string;
  time_column: string;
  value_column: string;
  operations?: string[];
  resample_freq?: string | null;
  rolling_window?: number;
}): Promise<TimeSeriesAnalysis> {
  return apiFetch<TimeSeriesAnalysis>("/timeseries/analyze", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
