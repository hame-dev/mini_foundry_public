"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type QualityRule = { id: string; column_name: string | null; rule_type: string; rule_value: string | null; severity: string };
type QualityResult = { id: string; rule_type: string; column_name: string | null; severity: string; passed: boolean; failed_records: number; message: string | null };
type QualityRun = { run_id: string; status: string; results: QualityResult[] };
type Freshness = { last_updated: string | null; age_seconds: number | null; window_seconds: number | null; status: string };
type StorageManifest = {
  id: string;
  dataset_version_id: string | null;
  storage_uri: string | null;
  file_count: number | null;
  total_bytes: number | null;
  content_hash: string | null;
  created_at: string;
};

const RULE_TYPES = ["not_null", "unique", "min", "max", "pattern"];

function statusBadge(status: string): string {
  if (status === "passed" || status === "fresh") return "badge badge-success";
  if (status === "failed" || status === "stale") return "badge badge-danger";
  if (status === "warning") return "badge badge-warning";
  return "badge";
}

function formatAge(s: number | null): string {
  if (s == null) return "—";
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

function formatBytes(n: number | null): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

export function QualitySection({ datasetId }: { datasetId: string }) {
  const [rules, setRules] = useState<QualityRule[]>([]);
  const [results, setResults] = useState<QualityResult[]>([]);
  const [freshness, setFreshness] = useState<Freshness | null>(null);
  const [manifests, setManifests] = useState<StorageManifest[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [columnName, setColumnName] = useState("");
  const [ruleType, setRuleType] = useState("not_null");
  const [ruleValue, setRuleValue] = useState("");
  const [severity, setSeverity] = useState("error");
  const [windowSeconds, setWindowSeconds] = useState("");

  const load = useCallback(async () => {
    try {
      const [r, res, f, m] = await Promise.all([
        apiFetch<QualityRule[]>(`/catalog/datasets/${datasetId}/quality-rules`),
        apiFetch<QualityResult[]>(`/catalog/datasets/${datasetId}/quality-results`).catch(() => []),
        apiFetch<Freshness>(`/catalog/datasets/${datasetId}/freshness`).catch(() => null),
        apiFetch<StorageManifest[]>(`/catalog/datasets/${datasetId}/storage-manifests`).catch(() => []),
      ]);
      setRules(r);
      setResults(res);
      setFreshness(f);
      setManifests(m);
      if (f?.window_seconds != null) setWindowSeconds(String(f.window_seconds));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load quality info");
    }
  }, [datasetId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function addRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await apiFetch(`/catalog/datasets/${datasetId}/quality-rules`, {
        method: "POST",
        body: JSON.stringify({ column_name: columnName || null, rule_type: ruleType, rule_value: ruleValue || null, severity }),
      });
      setColumnName("");
      setRuleValue("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add rule");
    }
  }

  async function deleteRule(id: string) {
    try {
      await apiFetch(`/catalog/datasets/${datasetId}/quality-rules/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete rule");
    }
  }

  async function runChecks() {
    setRunning(true);
    setError(null);
    try {
      const run = await apiFetch<QualityRun>(`/catalog/datasets/${datasetId}/quality-run`, { method: "POST" });
      setResults(run.results);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to run checks");
    } finally {
      setRunning(false);
    }
  }

  async function saveWindow() {
    try {
      const f = await apiFetch<Freshness>(`/catalog/datasets/${datasetId}/freshness`, {
        method: "PUT",
        body: JSON.stringify({ window_seconds: windowSeconds ? Number(windowSeconds) : null }),
      });
      setFreshness(f);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to set freshness window");
    }
  }

  const resultById = new Map(results.map((r) => [`${r.rule_type}:${r.column_name ?? ""}`, r]));

  return (
    <section className="app-card" style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <h2 className="section-title" style={{ margin: 0 }}>Quality &amp; freshness</h2>
        <button className="btn btn-primary" onClick={() => void runChecks()} disabled={running || rules.length === 0}>
          {running ? "Running…" : "Run checks"}
        </button>
      </div>
      {error ? <div style={{ color: "var(--danger)", marginTop: 8 }}>{error}</div> : null}

      {/* Freshness */}
      <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span className={statusBadge(freshness?.status ?? "unknown")}>{freshness?.status ?? "unknown"}</span>
        <span style={{ color: "var(--muted)", fontSize: 13 }}>
          age {formatAge(freshness?.age_seconds ?? null)}{freshness?.window_seconds != null ? ` / window ${formatAge(freshness.window_seconds)}` : ""}
        </span>
        <input className="input-dark" style={{ width: 160 }} placeholder="Freshness window (sec)" value={windowSeconds} onChange={(e) => setWindowSeconds(e.target.value)} />
        <button className="btn" onClick={() => void saveWindow()}>Save window</button>
      </div>

      <div style={{ marginTop: 16 }}>
        <h3 style={{ margin: "0 0 8px", fontSize: 13 }}>Storage manifests</h3>
        {manifests.length ? (
          <div className="overflow-auto">
            <table className="data-table" style={{ fontSize: 12 }}>
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Files</th>
                  <th>Bytes</th>
                  <th>Content hash</th>
                  <th>URI</th>
                </tr>
              </thead>
              <tbody>
                {manifests.slice(0, 5).map((m) => (
                  <tr key={m.id}>
                    <td>{new Date(m.created_at).toLocaleString()}</td>
                    <td>{m.file_count ?? "—"}</td>
                    <td>{formatBytes(m.total_bytes)}</td>
                    <td className="font-mono" style={{ fontSize: 11 }}>{m.content_hash?.slice(0, 18) ?? "—"}</td>
                    <td className="font-mono" style={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {m.storage_uri ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ color: "var(--muted)", fontSize: 13 }}>No version storage manifests recorded yet.</div>
        )}
      </div>

      {/* Rules + results */}
      <div style={{ marginTop: 16 }}>
        {rules.length ? (
          <table className="w-full" style={{ fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--muted)" }}>
                <th style={{ padding: "6px 8px" }}>Column</th>
                <th style={{ padding: "6px 8px" }}>Rule</th>
                <th style={{ padding: "6px 8px" }}>Severity</th>
                <th style={{ padding: "6px 8px" }}>Last result</th>
                <th style={{ padding: "6px 8px" }} />
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => {
                const r = resultById.get(`${rule.rule_type}:${rule.column_name ?? ""}`);
                return (
                  <tr key={rule.id} style={{ borderTop: "1px solid var(--line-soft)" }}>
                    <td style={{ padding: "6px 8px" }}>{rule.column_name || "—"}</td>
                    <td style={{ padding: "6px 8px" }} className="font-mono">{rule.rule_type}{rule.rule_value ? ` ${rule.rule_value}` : ""}</td>
                    <td style={{ padding: "6px 8px" }}>{rule.severity}</td>
                    <td style={{ padding: "6px 8px" }}>
                      {r ? (
                        <span className={r.passed ? "badge badge-success" : "badge badge-danger"}>
                          {r.passed ? "passed" : `failed (${r.failed_records})`}
                        </span>
                      ) : (
                        <span style={{ color: "var(--muted)" }}>not run</span>
                      )}
                    </td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }}>
                      <button className="btn" onClick={() => void deleteRule(rule.id)}>Delete</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div style={{ color: "var(--muted)", fontSize: 13 }}>No quality rules yet. Add one below.</div>
        )}
      </div>

      {/* Add rule */}
      <form onSubmit={addRule} style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <input className="input-dark" placeholder="column" value={columnName} onChange={(e) => setColumnName(e.target.value)} style={{ width: 140 }} />
        <select className="input-dark" value={ruleType} onChange={(e) => setRuleType(e.target.value)}>
          {RULE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <input className="input-dark" placeholder="value (min/max/pattern)" value={ruleValue} onChange={(e) => setRuleValue(e.target.value)} style={{ width: 180 }} />
        <select className="input-dark" value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="error">error</option>
          <option value="warn">warn</option>
        </select>
        <button className="btn" type="submit">Add rule</button>
      </form>
    </section>
  );
}
