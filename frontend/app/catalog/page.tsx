"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { Dataset } from "@/lib/types";

export default function CatalogPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    apiFetch<Dataset[]>("/catalog/datasets")
      .then(setDatasets)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return datasets;
    return datasets.filter(
      (d) =>
        d.name.toLowerCase().includes(q) ||
        `${d.schema_name}.${d.table_name}`.toLowerCase().includes(q)
    );
  }, [datasets, query]);

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header-eyebrow">Build · Catalog</div>
          <h1 className="page-header-title">Data catalog</h1>
          <div className="page-header-subtitle">
            All registered datasets, their physical mapping, and AI access policy.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link href="/catalog/lineage" className="btn-secondary">
            <span>Visual lineage</span>
          </Link>
          <Link href="/connectors/new" className="btn-primary">
            <span aria-hidden>＋</span>
            <span>New connector</span>
          </Link>
        </div>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 14,
          flexWrap: "wrap",
        }}
      >
        <div style={{ position: "relative", flex: "1 1 320px", maxWidth: 480 }}>
          <span
            aria-hidden
            style={{
              position: "absolute",
              left: 10,
              top: "50%",
              transform: "translateY(-50%)",
              color: "var(--muted-2)",
              fontSize: 13,
              pointerEvents: "none",
            }}
          >
            ⌕
          </span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter datasets by name or table…"
            style={{ width: "100%", padding: "7px 10px 7px 30px" }}
          />
        </div>
        <span className="badge">{filtered.length} of {datasets.length}</span>
      </div>

      {loading ? (
        <div className="app-card empty-state">
          <div className="empty-state-title">Loading datasets…</div>
        </div>
      ) : error ? (
        <div className="app-card empty-state">
          <div className="empty-state-title" style={{ color: "var(--danger)" }}>
            Failed to load catalog
          </div>
          <div className="empty-state-help">{error}</div>
        </div>
      ) : (
        <div className="app-card overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Physical table</th>
                <th style={{ textAlign: "right" }}>Rows</th>
                <th>AI policy</th>
                <th>Lineage</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5}>
                    <div className="empty-state">
                      <div className="empty-state-title">No datasets match.</div>
                      <div className="empty-state-help">
                        {datasets.length === 0
                          ? "Create a connector to ingest your first table."
                          : "Try a different search term."}
                      </div>
                    </div>
                  </td>
                </tr>
              ) : (
                filtered.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <Link href={`/catalog/${d.id}`} className="text-blue-600 hover:underline">
                        {d.name}
                      </Link>
                    </td>
                    <td>
                      <span className="font-mono" style={{ color: "var(--muted)", fontSize: 12 }}>
                        {d.schema_name}.{d.table_name}
                      </span>
                    </td>
                    <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                      {d.row_count?.toLocaleString() ?? "—"}
                    </td>
                    <td>
                      <span className={`badge ${policyClass(d.ai_policy)}`}>{d.ai_policy}</span>
                    </td>
                    <td>
                      {d.derived_from_pipeline_id ? (
                        <Link href={`/pipelines/${d.derived_from_pipeline_id}`} className="text-blue-600 hover:underline">
                          Pipeline output
                        </Link>
                      ) : (
                        <span style={{ color: "var(--muted-2)" }}>Source</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function policyClass(policy: string) {
  const p = policy?.toLowerCase() ?? "";
  if (p.includes("deny") || p.includes("block")) return "badge-danger";
  if (p.includes("redact") || p.includes("limit")) return "badge-warning";
  if (p.includes("allow")) return "badge-success";
  return "badge-accent";
}
