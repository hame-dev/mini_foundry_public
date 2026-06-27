"use client";

import { use, useCallback, useEffect, useMemo, useState } from "react";
import { ApiError } from "@/lib/api";
import { getResourceImpact, getResourceLineage, type ResourceImpact, type ResourceLineage } from "@/lib/lineage";
import { useActiveBranch } from "@/lib/branchContext";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { ErrorState, LoadingState } from "@/components/platform/States";

type Direction = "upstream" | "downstream" | "both";

export default function ResourceLineagePage({ params }: { params: Promise<{ resourceId: string }> }) {
  const { resourceId } = use(params);
  const [direction, setDirection] = useState<Direction>("both");
  const [depth, setDepth] = useState(2);
  const { branchName, setBranchName } = useActiveBranch();
  const [includeColumns, setIncludeColumns] = useState(true);
  const [columns, setColumns] = useState("");
  const [lineage, setLineage] = useState<ResourceLineage | null>(null);
  const [impact, setImpact] = useState<ResourceImpact | null>(null);
  const [activeTab, setActiveTab] = useState<"graph" | "impact">("graph");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextLineage, nextImpact] = await Promise.all([
        getResourceLineage(resourceId, { direction, depth, branch_name: branchName || undefined, include_columns: includeColumns }),
        getResourceImpact(resourceId, { depth, columns: columns || undefined }),
      ]);
      setLineage(nextLineage);
      setImpact(nextImpact);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load lineage.");
    } finally {
      setLoading(false);
    }
  }, [resourceId, direction, depth, branchName, includeColumns, columns]);

  useEffect(() => { void load(); }, [load]);

  const nodesById = useMemo(() => new Map((lineage?.nodes ?? []).map((node) => [node.id, node])), [lineage]);
  const hiddenLineageCount = lineage?.hidden_nodes?.count ?? Number((lineage as unknown as { hidden_node_count?: number } | null)?.hidden_node_count ?? 0);
  const hiddenImpactCount = impact?.hidden_nodes?.count ?? Number((impact as unknown as { hidden_node_count?: number } | null)?.hidden_node_count ?? 0);

  return (
    <div className="space-y-5">
      <ResourceHeader title="Resource lineage" type="Lineage" status={lineage ? `${lineage.edges.length} edges` : "Loading"} />

      <section className="app-card p-3">
        <div className="grid gap-3 md:grid-cols-5">
          <label className="text-xs">
            <span className="mb-1 block text-[var(--muted)]">Direction</span>
            <select className="input-dark" value={direction} onChange={(event) => setDirection(event.target.value as Direction)}>
              <option value="both">Both</option>
              <option value="upstream">Upstream</option>
              <option value="downstream">Downstream</option>
            </select>
          </label>
          <label className="text-xs">
            <span className="mb-1 block text-[var(--muted)]">Depth</span>
            <input className="input-dark" type="number" min={1} max={5} value={depth} onChange={(event) => setDepth(Number(event.target.value) || 1)} />
          </label>
          <label className="text-xs">
            <span className="mb-1 block text-[var(--muted)]">Branch</span>
            <input className="input-dark" value={branchName} onChange={(event) => setBranchName(event.target.value)} placeholder="main" />
          </label>
          <label className="text-xs">
            <span className="mb-1 block text-[var(--muted)]">Impact columns</span>
            <input className="input-dark" value={columns} onChange={(event) => setColumns(event.target.value)} placeholder="customer_id,status" />
          </label>
          <label className="flex items-end gap-2 text-xs">
            <input type="checkbox" checked={includeColumns} onChange={(event) => setIncludeColumns(event.target.checked)} />
            <span className="pb-2">Column mappings</span>
          </label>
        </div>
      </section>

      <div className="flex gap-2">
        <button className={activeTab === "graph" ? "btn-primary text-xs" : "btn-ghost text-xs"} onClick={() => setActiveTab("graph")}>Graph</button>
        <button className={activeTab === "impact" ? "btn-primary text-xs" : "btn-ghost text-xs"} onClick={() => setActiveTab("impact")}>Impact</button>
      </div>

      {loading ? <LoadingState label="Loading lineage..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && !error && lineage && activeTab === "graph" ? (
        <div className="grid gap-3 lg:grid-cols-[300px_minmax(0,1fr)]">
          <section className="app-card p-3">
            <h2 className="section-header-title mb-2">Nodes</h2>
            <ul className="space-y-1 text-sm">
              {lineage.nodes.map((node) => (
                <li key={node.id} className="rounded border border-[var(--line-soft)] p-2">
                  <div className="font-medium">{node.name}</div>
                  <div className="text-xs text-[var(--muted)]">{node.resource_type}</div>
                </li>
              ))}
            </ul>
            {hiddenLineageCount ? <p className="mt-3 text-xs text-[var(--muted)]">{hiddenLineageCount} hidden nodes omitted by permissions.</p> : null}
          </section>
          <section className="app-card p-3">
            <h2 className="section-header-title mb-2">Edges</h2>
            <ul className="space-y-2 text-sm">
              {lineage.edges.map((edge) => {
                const source = edge.source_resource_id ? nodesById.get(edge.source_resource_id) : null;
                const target = edge.target_resource_id ? nodesById.get(edge.target_resource_id) : null;
                const mappings = Array.isArray(edge.metadata.column_mappings) ? edge.metadata.column_mappings as Array<Record<string, unknown>> : [];
                return (
                  <li key={edge.id} className="rounded border border-[var(--line-soft)] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-medium">{source?.name ?? "Hidden source"} to {target?.name ?? "Hidden target"}</span>
                      <span className="text-xs text-[var(--muted)]">{edge.edge_type}</span>
                    </div>
                    {mappings.length ? (
                      <div className="mt-2 grid gap-1 text-xs text-[var(--muted)]">
                        {mappings.slice(0, 6).map((mapping, index) => (
                          <span key={index}>{String(mapping.source_column)} to {String(mapping.target_column)} - {String(mapping.transform || "direct")}</span>
                        ))}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
      ) : null}

      {!loading && !error && impact && activeTab === "impact" ? (
        <section className="app-card p-3">
          <h2 className="section-header-title mb-2">Impact analysis</h2>
          <div className="mb-3 flex flex-wrap gap-2 text-xs text-[var(--muted)]">
            {Object.entries(impact.by_type).map(([type, count]) => <span key={type} className="topbar-pill">{type}: {count}</span>)}
            {hiddenImpactCount ? <span className="topbar-pill">{hiddenImpactCount} hidden</span> : null}
          </div>
          <ul className="space-y-1 text-sm">
            {impact.affected.map((node) => (
              <li key={node.id} className="flex items-center justify-between rounded border border-[var(--line-soft)] p-2">
                <span>{node.name}</span>
                <span className="text-xs text-[var(--muted)]">{node.resource_type}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
