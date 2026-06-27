"use client";
import Link from "next/link";
import { use, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { DatasetDetail } from "@/lib/types";
import { QualitySection } from "@/components/data/QualitySection";
import { ResourceComments } from "@/components/platform/ResourceComments";

type PreviewResponse = { rows: Record<string, unknown>[]; row_count: number };

export default function DatasetDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<DatasetDetail>(`/catalog/datasets/${id}`)
      .then(setDetail)
      .catch((e) => setError(e.message));
    apiFetch<PreviewResponse>(`/catalog/datasets/${id}/preview?limit=50`)
      .then(setPreview)
      .catch(() => undefined);
  }, [id]);

  if (error)
    return (
      <div className="app-card empty-state">
        <div className="empty-state-title" style={{ color: "var(--danger)" }}>
          Could not load dataset
        </div>
        <div className="empty-state-help">{error}</div>
      </div>
    );
  if (!detail)
    return (
      <div className="app-card empty-state">
        <div className="empty-state-title">Loading dataset…</div>
      </div>
    );

  const previewCols = preview?.rows.length ? Object.keys(preview.rows[0]) : [];
  const profileColumns = (detail.profile?.columns ?? {}) as Record<string, { classifications?: string[]; sensitivity?: string; suggested_markings?: string[]; steward_confirmed?: boolean }>;

  async function confirmClassification(columnName: string) {
    const profile = profileColumns[columnName];
    await apiFetch(`/catalog/datasets/${id}/classifications/confirm`, {
      method: "POST",
      body: JSON.stringify({
        column_name: columnName,
        classifications: profile?.classifications ?? [],
        sensitivity: profile?.sensitivity ?? "internal",
        suggested_markings: profile?.suggested_markings ?? [],
      }),
    });
    const refreshed = await apiFetch<DatasetDetail>(`/catalog/datasets/${id}`);
    setDetail(refreshed);
  }

  return (
    <div className="space-y-6">
      <header className="page-header" style={{ alignItems: "flex-start", display: "flex", justifyContent: "space-between", width: "100%" }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="page-header-eyebrow">Dataset</div>
          <h1 className="page-header-title">{detail.name}</h1>
          <div className="stat-row" style={{ marginTop: 8 }}>
            <span className="font-mono" style={{ color: "var(--muted)" }}>
              {detail.schema_name}.{detail.table_name}
            </span>
            <span className="dot" aria-hidden>·</span>
            <span style={{ fontVariantNumeric: "tabular-nums" }}>
              {detail.row_count?.toLocaleString() ?? "—"} rows
            </span>
            <span className="dot" aria-hidden>·</span>
            <span className="badge badge-accent">{detail.ai_policy}</span>
            {detail.derived_from_pipeline_id ? (
              <>
                <span className="dot" aria-hidden>·</span>
                <Link href={`/pipelines/${detail.derived_from_pipeline_id}`} className="text-blue-600 hover:underline">
                  Pipeline output
                </Link>
              </>
            ) : null}
          </div>
          {detail.description && (
            <p
              style={{
                marginTop: 12,
                maxWidth: 760,
                color: "var(--text-2)",
                fontSize: 13,
                lineHeight: 1.55,
              }}
            >
              {detail.description}
            </p>
          )}

          {/* Governance Metadata Badges */}
          <div className="flex flex-wrap gap-6 mt-4 pt-3" style={{ borderTop: "1px solid var(--line-soft)" }}>
            {detail.security_markings && detail.security_markings.length > 0 && (
              <div className="flex items-center gap-1.5">
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--danger)" }}>Markings:</span>
                {detail.security_markings.map((m: any) => (
                  <span key={m} className="badge badge-danger">{m}</span>
                ))}
              </div>
            )}
            {detail.stewards && detail.stewards.length > 0 && (
              <div className="flex items-center gap-1.5">
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted-2)" }}>Stewards:</span>
                {detail.stewards.map((s: any) => (
                  <span key={s} className="badge">{s}</span>
                ))}
              </div>
            )}
            {detail.tags && detail.tags.length > 0 && (
              <div className="flex items-center gap-1.5">
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--accent)" }}>Tags:</span>
                {detail.tags.map((t: any) => (
                  <span key={t} className="badge badge-accent">{t}</span>
                ))}
              </div>
            )}
            {detail.glossary_terms && detail.glossary_terms.length > 0 && (
              <div className="flex items-center gap-1.5">
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--success)" }}>Glossary:</span>
                {detail.glossary_terms.map((g: any) => (
                  <span key={g} className="badge badge-success">{g}</span>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <Link href={`/data/datasets/${id}/branches`} className="btn-ghost text-sm font-semibold">
            Branches
          </Link>
          <Link href={`/data/datasets/${id}/explore`} className="btn-primary text-sm font-semibold">
            Visual Analysis (Contour)
          </Link>
        </div>
      </header>

      <Section
        title="Schema"
        eyebrow="Columns"
        count={detail.columns.length}
      >
        <div className="app-card overflow-hidden">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Sample values</th>
                <th>Classification</th>
              </tr>
            </thead>
            <tbody>
              {detail.columns.map((c) => (
                <tr key={c.name}>
                  <td className="font-mono" style={{ color: "var(--text)" }}>
                    {c.name}
                  </td>
                  <td>
                    <span className="badge">{c.data_type ?? "—"}</span>
                  </td>
                  <td
                    className="font-mono"
                    style={{ color: "var(--muted)", fontSize: 11.5 }}
                  >
                    {c.sample_values ? JSON.stringify(c.sample_values) : "—"}
                  </td>
                  <td>
                    <div className="flex flex-wrap items-center gap-1">
                      {(profileColumns[c.name]?.classifications ?? []).map((label) => <span key={label} className="badge badge-accent">{label}</span>)}
                      {profileColumns[c.name]?.sensitivity ? <span className="badge">{profileColumns[c.name]?.sensitivity}</span> : null}
                      {(profileColumns[c.name]?.suggested_markings ?? []).map((marking) => <span key={marking} className="badge badge-danger">{marking}</span>)}
                      {profileColumns[c.name]?.steward_confirmed ? (
                        <span className="badge badge-success">confirmed</span>
                      ) : profileColumns[c.name] ? (
                        <button type="button" className="toolbar-button" onClick={() => void confirmClassification(c.name)}>Confirm</button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section
        title="Preview"
        eyebrow="Rows"
        count={preview?.rows.length}
      >
        <div className="app-card overflow-auto" style={{ maxHeight: 520 }}>
          {preview ? (
            <table className="data-table" style={{ fontSize: 12 }}>
              <thead>
                <tr>
                  {previewCols.map((c) => (
                    <th key={c}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r, i) => (
                  <tr key={i}>
                    {previewCols.map((c) => (
                      <td key={c} className="font-mono" style={{ fontSize: 11.5 }}>
                        {String(r[c] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty-state">
              <div className="empty-state-title">No preview available</div>
              <div className="empty-state-help">
                Your role may not have read access to the underlying rows.
              </div>
            </div>
          )}
        </div>
      </Section>

      <QualitySection datasetId={id} />
      <ResourceComments resourceId={detail.resource_id} />
    </div>
  );
}

function Section({
  title,
  eyebrow,
  count,
  children,
}: {
  title: string;
  eyebrow?: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 10,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          {eyebrow && (
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "var(--muted-2)",
              }}
            >
              {eyebrow}
            </span>
          )}
          <h2 style={{ fontSize: 15, margin: 0 }}>{title}</h2>
        </div>
        {typeof count === "number" && <span className="badge">{count}</span>}
      </div>
      {children}
    </section>
  );
}
