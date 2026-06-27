"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { ResourceHeader, ResourceToolbar } from "@/components/foundry/FoundryPrimitives";

type ExploreResult = {
  id: string;
  kind: "dataset" | "pipeline" | "object" | "saved_query";
  name: string;
  subtitle: string | null;
  description: string | null;
  ai_policy: string | null;
  owner_id: string | null;
  updated_at: string | null;
  href: string;
  dataset_id?: string | null;
  output_dataset_id?: string | null;
};

const KIND_LABEL: Record<ExploreResult["kind"], string> = {
  dataset: "Dataset",
  pipeline: "Pipeline",
  object: "Object",
  saved_query: "Saved query",
};

const KIND_BADGE: Record<ExploreResult["kind"], string> = {
  dataset: "badge-accent",
  pipeline: "badge-success",
  object: "badge-warning",
  saved_query: "badge",
};

export default function ExplorePage() {
  const [query, setQuery] = useState("");
  const [kinds, setKinds] = useState<Set<ExploreResult["kind"]>>(
    new Set(["dataset", "pipeline", "object", "saved_query"]),
  );
  const [policy, setPolicy] = useState<string>("");
  const [results, setResults] = useState<ExploreResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ExploreResult | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    if (kinds.size < 4) params.set("kinds", Array.from(kinds).join(","));
    if (policy) params.set("policy", policy);
    apiFetch<{ results: ExploreResult[]; total: number }>(`/explore?${params.toString()}`)
      .then((r) => {
        setResults(r.results);
        if (!selected && r.results.length > 0) setSelected(r.results[0]);
      })
      .catch((e) => {
        if (!ctrl.signal.aborted) setError(e.message);
      })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, kinds, policy]);

  function toggleKind(k: ExploreResult["kind"]) {
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      if (next.size === 0) {
        // never empty
        next.add(k);
      }
      return next;
    });
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = { dataset: 0, pipeline: 0, object: 0, saved_query: 0 };
    for (const r of results) c[r.kind] = (c[r.kind] ?? 0) + 1;
    return c;
  }, [results]);

  return (
    <div>
      <ResourceHeader
        eyebrow="Object Explorer"
        title="Explore Objects, Datasets, And Resources"
        subtitle="Search business objects, datasets, pipeline outputs, and saved SQL with filters, result actions, and linked-resource context."
        tabs={[{ label: "Explore", id: "Explore" }, { label: "Results", id: "Results" }, { label: "Lists", id: "Lists" }]}
        activeTab="Explore"
      />
      <ResourceToolbar>
        <button className="btn-ghost">Custom layout</button>
        <button className="btn-ghost">Compare</button>
        <button className="btn-ghost">Actions</button>
        <button className="btn-ghost">Analyze using SQL</button>
      </ResourceToolbar>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "220px 1fr 360px",
          gap: 14,
          minHeight: 520,
        }}
      >
        {/* Facets */}
        <aside
          style={{
            border: "1px solid var(--line)",
            background: "var(--panel)",
            borderRadius: 3,
            padding: 12,
            display: "grid",
            gap: 14,
            alignContent: "start",
          }}
        >
          <div>
            <FacetLabel>Kinds</FacetLabel>
            <div style={{ display: "grid", gap: 4 }}>
              {(["dataset", "pipeline", "object", "saved_query"] as const).map((k) => (
                <label
                  key={k}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 12.5,
                    cursor: "pointer",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={kinds.has(k)}
                    onChange={() => toggleKind(k)}
                  />
                  <span style={{ flex: 1 }}>{KIND_LABEL[k]}</span>
                  <span style={{ color: "var(--muted-2)", fontSize: 11 }}>{counts[k] ?? 0}</span>
                </label>
              ))}
            </div>
          </div>
          <div>
            <FacetLabel>AI policy</FacetLabel>
            <select
              value={policy}
              onChange={(e) => setPolicy(e.target.value)}
              style={{ width: "100%", padding: "6px 8px", fontSize: 12 }}
            >
              <option value="">Any</option>
              <option value="local_only">local_only</option>
              <option value="metadata_only">metadata_only</option>
              <option value="cloud_allowed">cloud_allowed</option>
            </select>
          </div>
        </aside>

        {/* Results */}
        <section
          style={{
            border: "1px solid var(--line)",
            background: "var(--panel)",
            borderRadius: 3,
            display: "grid",
            gridTemplateRows: "auto 1fr",
            minHeight: 0,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "10px 12px",
              borderBottom: "1px solid var(--line-soft)",
              background: "var(--panel-2)",
              display: "flex",
              gap: 10,
              alignItems: "center",
            }}
          >
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search datasets, pipelines, objects, saved queries…"
              style={{ flex: 1, padding: "7px 10px" }}
            />
            <span className="badge">{results.length}</span>
          </div>
          <div style={{ overflowY: "auto", minHeight: 0 }}>
            {loading ? (
              <div className="empty-state">
                <div className="empty-state-title">Searching…</div>
              </div>
            ) : error ? (
              <div className="empty-state">
                <div className="empty-state-title" style={{ color: "var(--danger)" }}>
                  Failed
                </div>
                <div className="empty-state-help">{error}</div>
              </div>
            ) : results.length === 0 ? (
              <div className="empty-state">
                <div className="empty-state-title">Nothing matched</div>
                <div className="empty-state-help">Try a different search or facet.</div>
              </div>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {results.map((r) => (
                  <li
                    key={`${r.kind}:${r.id}`}
                    onClick={() => setSelected(r)}
                    style={{
                      padding: "10px 14px",
                      borderBottom: "1px solid var(--line-soft)",
                      cursor: "pointer",
                      background:
                        selected && selected.kind === r.kind && selected.id === r.id
                          ? "var(--accent-soft)"
                          : "transparent",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span className={`badge ${KIND_BADGE[r.kind]}`}>{KIND_LABEL[r.kind]}</span>
                      <span style={{ fontWeight: 600, fontSize: 13 }}>{r.name}</span>
                      <span style={{ marginLeft: "auto", color: "var(--muted-2)", fontSize: 11 }}>
                        {r.updated_at ? new Date(r.updated_at).toLocaleDateString() : ""}
                      </span>
                    </div>
                    {r.subtitle ? (
                      <div
                        className="font-mono"
                        style={{ color: "var(--muted)", fontSize: 11, marginTop: 2 }}
                      >
                        {r.subtitle}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* Detail / send-to */}
        <aside
          style={{
            border: "1px solid var(--line)",
            background: "var(--panel)",
            borderRadius: 3,
            padding: 14,
            overflowY: "auto",
          }}
        >
          {selected ? <DetailPane result={selected} /> : (
            <div style={{ color: "var(--muted)", fontSize: 12.5 }}>
              Select an item to see actions.
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function FacetLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        color: "var(--muted-2)",
        marginBottom: 6,
      }}
    >
      {children}
    </div>
  );
}

function DetailPane({ result }: { result: ExploreResult }) {
  const datasetId =
    result.kind === "dataset"
      ? result.id
      : result.kind === "pipeline"
        ? result.output_dataset_id ?? null
        : result.kind === "object"
          ? result.dataset_id ?? null
          : null;

  return (
    <div style={{ display: "grid", gap: 12 }}>
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
          {KIND_LABEL[result.kind]}
        </div>
        <h2 style={{ margin: "4px 0 0", fontSize: 17 }}>{result.name}</h2>
        {result.subtitle ? (
          <div className="font-mono" style={{ color: "var(--muted)", fontSize: 11.5, marginTop: 4 }}>
            {result.subtitle}
          </div>
        ) : null}
      </div>
      {result.description ? (
        <p style={{ margin: 0, fontSize: 12.5, color: "var(--text-2)", lineHeight: 1.55 }}>
          {result.description}
        </p>
      ) : null}
      {result.ai_policy ? (
        <div>
          <span className="badge badge-accent">{result.ai_policy}</span>
        </div>
      ) : null}
      <div
        style={{
          marginTop: 4,
          paddingTop: 10,
          borderTop: "1px solid var(--line-soft)",
          display: "grid",
          gap: 6,
        }}
      >
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--muted-2)",
          }}
        >
          Open in
        </div>
        <Link className="btn-ghost" href={result.href}>
          {KIND_LABEL[result.kind]} page
        </Link>
        {datasetId ? (
          <>
            <Link className="btn-ghost" href={`/dashboards/new?dataset_id=${datasetId}`}>
              New dashboard from this
            </Link>
            <Link className="btn-ghost" href={`/notebooks/new?dataset_id=${datasetId}`}>
              New notebook from this
            </Link>
            <Link className="btn-ghost" href={`/sql?dataset_id=${datasetId}`}>
              Query in SQL
            </Link>
          </>
        ) : null}
      </div>
    </div>
  );
}
