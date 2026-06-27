"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { apiFetch } from "@/lib/api";
import type {
  PipelineDetail,
  PipelineEdge,
  PipelineNode,
  NodeType,
  PreviewOut,
  RunOut,
} from "@/lib/pipelines";
import type { Dataset } from "@/lib/types";

import { DatasetPalette } from "@/components/pipelines/DatasetPalette";
import { NodeTypePalette } from "@/components/pipelines/NodeTypePalette";
import { NodeInspector } from "@/components/pipelines/NodeInspector";
import { PreviewPanel } from "@/components/pipelines/PreviewPanel";
import { AiPipelinePrompt } from "@/components/pipelines/AiPipelinePrompt";
import { PipelineCanvas } from "@/components/pipelines/PipelineCanvas";
import { BottomDrawer, ResourceHeader, ResourceToolbar } from "@/components/foundry/FoundryPrimitives";
import { ResourceComments } from "@/components/platform/ResourceComments";
import { useActiveBranch } from "@/lib/branchContext";

export default function PipelineEditorPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();

  const [pipeline, setPipeline] = useState<PipelineDetail | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [nodes, setNodes] = useState<PipelineNode[]>([]);
  const [edges, setEdges] = useState<PipelineEdge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<Set<string>>(new Set());

  const [previewOpen, setPreviewOpen] = useState(false);
  const [preview, setPreview] = useState<PreviewOut | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [validation, setValidation] = useState<{ status: string; warnings: any[]; errors: any[] } | null>(null);
  const [name, setName] = useState("");
  const [dirty, setDirty] = useState(false);
  const [materializationType, setMaterializationType] = useState<"view" | "table" | "parquet">("view");
  const [queuedJobId, setQueuedJobId] = useState<string | null>(null);
  const [platformResourceId, setPlatformResourceId] = useState<string | null>(null);
  const { branchName } = useActiveBranch();
  const lastGraph = useRef<{ nodes: PipelineNode[]; edges: PipelineEdge[] }>({ nodes: [], edges: [] });

  function rid(prefix: string) {
    return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
  }

  function defaultConfigFor(type: NodeType): Record<string, unknown> {
    switch (type) {
      case "join":
        return { join_type: "inner", left_keys: [], right_keys: [] };
      case "filter":
        return { where: "" };
      case "formula":
        return { columns: [] };
      case "select":
        return { columns: [], rename: {} };
      case "trained_model":
        return { model_id: "", version_id: "", prediction_column: "prediction" };
      case "union":
        return { distinct: false };
      case "output":
        return { name: "pipeline_output", materialize: "view" };
      default:
        return {};
    }
  }

  // initial load
  useEffect(() => {
    const branchQuery = branchName && branchName !== "main" ? `?branch_name=${encodeURIComponent(branchName)}` : "";
    apiFetch<PipelineDetail>(`/pipelines/${id}${branchQuery}`)
      .then((p) => {
        setPipeline(p);
        setName(p.name);
        setNodes(p.nodes);
        setEdges(p.edges);
        setMaterializationType(p.materialization_type || "view");
        lastGraph.current = { nodes: p.nodes, edges: p.edges };
        apiFetch("/activity/track", {
          method: "POST",
          body: JSON.stringify({ resource_type: "pipeline", resource_id: p.id, title: p.name, path: `/pipelines/${p.id}` }),
        }).catch(() => {});
      })
      .catch((e) => setError(e.message));
    apiFetch<Dataset[]>("/catalog/datasets")
      .then(setDatasets)
      .catch(() => undefined);
  }, [id, branchName]);

  useEffect(() => {
    apiFetch<{ id: string; object_id: string | null }[]>("/platform/resources?resource_type=pipeline&limit=500")
      .then((rows) => setPlatformResourceId(rows.find((row) => row.object_id === id)?.id ?? null))
      .catch(() => setPlatformResourceId(null));
  }, [id]);

  useEffect(() => {
    if (!queuedJobId || !pipeline) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const job = await apiFetch<{ status: string }>(`/jobs/${queuedJobId}`);
        if (cancelled) return;
        if (["succeeded", "failed", "cancelled", "timed_out"].includes(job.status)) {
          setQueuedJobId(null);
          const branchQuery = branchName && branchName !== "main" ? `?branch_name=${encodeURIComponent(branchName)}` : "";
          const fresh = await apiFetch<PipelineDetail>(`/pipelines/${id}${branchQuery}`);
          if (!cancelled) setPipeline(fresh);
        }
      } catch {
        // keep polling until terminal state or navigation
      }
    };
    const timer = window.setInterval(() => void poll(), 2000);
    void poll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [queuedJobId, pipeline, id, branchName]);

  const pipelineTabs = useMemo(
    () => [
      { label: "Graph", href: `/build/pipelines/${id}/graph` },
      { label: "Builds", href: `/build/pipelines/${id}/builds` },
      { label: "Schedules", href: `/build/pipelines/${id}/schedules` },
      { label: "Lineage", href: `/build/pipelines/${id}/lineage` },
      { label: "Branches", href: `/build/pipelines/${id}/branches` },
      { label: "Expectations", href: `/build/pipelines/${id}/expectations` },
    ],
    [id],
  );

  const selectedNode = useMemo(
    () => nodes.find((n) => n.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId],
  );

  const onGraphChange = useCallback(
    (g: { nodes: PipelineNode[]; edges: PipelineEdge[] }) => {
      setNodes(g.nodes);
      setEdges(g.edges);
      lastGraph.current = g;
      setDirty(true);
    },
    [],
  );

  function patchSelectedNode(patch: Partial<PipelineNode>) {
    if (!selectedNode) return;
    setNodes((prev) => prev.map((n) => (n.id === selectedNode.id ? { ...n, ...patch } : n)));
    setDirty(true);
  }

  function deleteSelectedNode() {
    if (!selectedNode) return;
    setNodes((prev) => prev.filter((n) => n.id !== selectedNode.id));
    setEdges((prev) =>
      prev.filter((e) => e.source_node_id !== selectedNode.id && e.target_node_id !== selectedNode.id),
    );
    setSelectedNodeId(null);
    setDirty(true);
  }

  function toggleDataset(id: string) {
    setSelectedDatasetIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function addSelectedDatasets() {
    const existing = new Set(
      nodes
        .filter((n) => n.node_type === "source")
        .map((n) => (n.config as { dataset_id?: string }).dataset_id)
        .filter(Boolean),
    );
    const ids = Array.from(selectedDatasetIds).filter((ds) => !existing.has(ds));
    if (!ids.length) return;
    const offset = nodes.length;
    const nextNodes: PipelineNode[] = ids.map((datasetId, i) => ({
      id: rid("n"),
      node_type: "source",
      position: { x: 80, y: 90 + (offset + i) * 92 },
      config: { dataset_id: datasetId },
    }));
    setNodes((prev) => [...prev, ...nextNodes]);
    setSelectedDatasetIds(new Set());
    setDirty(true);
  }

  function addTransform(type: NodeType) {
    const index = nodes.length;
    const node: PipelineNode = {
      id: rid("n"),
      node_type: type,
      position: { x: 420 + (index % 3) * 220, y: 120 + Math.floor(index / 3) * 130 },
      config: defaultConfigFor(type),
    };
    setNodes((prev) => [...prev, node]);
    setSelectedNodeId(node.id);
    setDirty(true);
  }

  async function save() {
    if (!pipeline) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await apiFetch<PipelineDetail>(`/pipelines/${pipeline.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name,
          nodes,
          edges,
          materialization_type: materializationType,
          branch_name: branchName || "main",
        }),
      });
      setPipeline(updated);
      setNodes(updated.nodes);
      setEdges(updated.edges);
      setDirty(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setSaving(false);
    }
  }

  async function runPreview() {
    if (!pipeline) return;
    setPreviewOpen(true);
    setValidation(null);
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      // save first if dirty, so backend has the latest graph
      if (dirty) await save();
      const res = await apiFetch<PreviewOut>(`/pipelines/${pipeline.id}/preview`, {
        method: "POST",
        body: JSON.stringify({ limit: 100, branch_name: branchName || "main" }),
      });
      setPreview(res);
    } catch (e: unknown) {
      setPreviewError(e instanceof Error ? e.message : "preview failed");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function runPipeline() {
    if (!pipeline) return;
    if (dirty) await save();
    setRunning(true);
    setError(null);
    try {
      const res = await apiFetch<RunOut>(`/pipelines/${pipeline.id}/run`, { method: "POST" });
      if (res.status === "error") {
        setError(res.error || "run failed");
      } else if (res.status === "queued") {
        setPipeline((prev) => prev ? { ...prev, last_run_status: "queued" } : prev);
        if (res.job_id) setQueuedJobId(res.job_id);
      } else {
        // Refresh summary so the badge/output_dataset_id update.
        const fresh = await apiFetch<PipelineDetail>(`/pipelines/${pipeline.id}`);
        setPipeline(fresh);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "run failed");
    } finally {
      setRunning(false);
    }
  }

  async function validateGraph() {
    if (!pipeline) return;
    if (dirty) await save();
    setError(null);
    try {
      const result = await apiFetch<{ status: string; warnings: any[]; errors: any[] }>(`/pipelines/${pipeline.id}/validate`, {
        method: "POST",
      });
      setValidation(result);
      setPreviewOpen(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "validation failed");
    }
  }

  function applyAiResult(
    aiName: string,
    desc: string | null,
    aiNodes: PipelineNode[],
    aiEdges: PipelineEdge[],
  ) {
    setName(aiName);
    setNodes(aiNodes);
    setEdges(aiEdges);
    setDirty(true);
    setAiOpen(false);
    if (pipeline && desc) {
      setPipeline({ ...pipeline, description: desc });
    }
  }

  if (error && !pipeline) {
    return (
      <div className="app-card empty-state">
        <div className="empty-state-title" style={{ color: "var(--danger)" }}>
          Could not load pipeline
        </div>
        <div className="empty-state-help">{error}</div>
      </div>
    );
  }
  if (!pipeline) {
    return (
      <div className="app-card empty-state">
        <div className="empty-state-title">Loading pipeline…</div>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateRows: "auto auto 1fr auto",
        gap: 8,
        minHeight: "calc(100vh - 96px)",
        width: "100%",
        maxWidth: "none",
      }}
    >
      <ResourceHeader
        eyebrow="Pipeline Builder"
        title={name || pipeline.name}
        subtitle={pipeline.description ?? "Visual graph for dataset transforms, ontology joins, and materialized outputs."}
        status={pipeline.last_run_status ?? "draft"}
        tabs={pipelineTabs}
        activeTab="Graph"
        meta={
          <>
            <span className="badge badge-accent">{pipeline.ai_policy}</span>
            {pipeline.output_dataset_id ? (
              <Link href={`/data/datasets/${pipeline.output_dataset_id}`} className="badge badge-info">
                Output dataset
              </Link>
            ) : null}
            {queuedJobId ? (
              <Link href={`/operations/jobs/${queuedJobId}`} className="badge badge-info">
                Job {queuedJobId.slice(0, 8)}…
              </Link>
            ) : null}
            {pipeline.materialized_rows != null ? (
              <span className="badge badge-success">{pipeline.materialized_rows.toLocaleString()} rows</span>
            ) : null}
          </>
        }
        actions={
          <>
            <button type="button" className="btn-ghost" onClick={save} disabled={saving || !dirty}>{saving ? "Saving..." : dirty ? "Save" : "Saved"}</button>
            <button type="button" className="btn-ghost" onClick={validateGraph}>Validate</button>
            <button type="button" className="btn-primary" onClick={runPipeline} disabled={running}>{running ? "Running..." : "Run"}</button>
            <button
              type="button"
              className="btn-ghost"
              onClick={async () => {
                if (!confirm("Delete this pipeline?")) return;
                await apiFetch(`/pipelines/${pipeline.id}`, { method: "DELETE" });
                router.push("/build/pipelines");
              }}
            >
              Delete
            </button>
          </>
        }
      />
      <ResourceToolbar>
        <button className="btn-ghost" onClick={addSelectedDatasets}>Add datasets</button>
        <div
          title="Choose how pipeline output is stored"
          style={{
            display: "flex",
            border: "1px solid var(--line)",
            borderRadius: 4,
            overflow: "hidden",
            fontSize: 11,
            fontWeight: 600,
          }}
        >
          {(["view", "table", "parquet"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => { setMaterializationType(m); setDirty(true); }}
              style={{
                padding: "5px 9px",
                background: materializationType === m ? "var(--accent)" : "transparent",
                color: materializationType === m ? "#fff" : "var(--muted)",
                border: "none",
                cursor: "pointer",
                textTransform: "uppercase",
                letterSpacing: 0,
              }}
            >
              {m}
            </button>
          ))}
        </div>
        {(["join", "filter", "formula", "select", "union", "output"] as NodeType[]).map((t) => (
          <button key={t} className="btn-ghost" onClick={() => addTransform(t)}>{t}</button>
        ))}
        <button type="button" className="btn-ghost" onClick={() => setAiOpen(true)}>AIP</button>
        <button type="button" className="btn-ghost" onClick={runPreview}>Preview</button>
      </ResourceToolbar>

      {error ? (
        <div
          style={{
            padding: "8px 10px",
            border: "1px solid rgba(255,111,125,0.35)",
            background: "var(--danger-soft)",
            color: "var(--danger)",
            borderRadius: 3,
            fontSize: 12,
          }}
        >
          {error}
        </div>
      ) : null}

      {/* Builder workspace: palette · graph · inspector, with preview as a bottom drawer. */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "280px minmax(0, 1fr) 360px",
          gridTemplateRows: previewOpen ? "minmax(0, 1fr) 300px" : "minmax(0, 1fr)",
          gap: 8,
          minHeight: 0,
        }}
      >
        <div
          style={{
            gridRow: previewOpen ? "1 / 3" : "1",
            display: "grid",
            gridTemplateRows: "1fr",
            border: "1px solid var(--line)",
            borderRadius: 3,
            background: "var(--panel)",
            minHeight: 0,
            overflow: "hidden",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
            <DatasetPalette
              datasets={datasets}
              selectedIds={selectedDatasetIds}
              onToggleDataset={toggleDataset}
              onAddSelected={addSelectedDatasets}
            />
            <div style={{ padding: "0 12px 12px" }}>
              <NodeTypePalette onAddType={addTransform} />
            </div>
          </div>
        </div>

        <div
          style={{
            position: "relative",
            border: "1px solid var(--line)",
            borderRadius: 3,
            overflow: "hidden",
            minHeight: 0,
            background: "var(--bg-2)",
          }}
        >
          <PipelineCanvas
            initialNodes={nodes}
            initialEdges={edges}
            onChange={onGraphChange}
            onSelectNode={setSelectedNodeId}
            onSelectEdge={setSelectedEdgeId}
            selectedNodeId={selectedNodeId}
            selectedEdgeId={selectedEdgeId}
            datasets={datasets}
          />
          {aiOpen ? <AiPipelinePrompt onGenerated={applyAiResult} onClose={() => setAiOpen(false)} /> : null}
        </div>

        <div
          style={{
            border: "1px solid var(--line)",
            borderRadius: 3,
            background: "var(--panel)",
            padding: 14,
            overflowY: "auto",
            minHeight: 0,
          }}
        >
          {selectedNode ? (
            <NodeInspector
              node={selectedNode}
              datasets={datasets}
              onChange={patchSelectedNode}
              onDelete={deleteSelectedNode}
            />
          ) : (
            <div style={{ color: "var(--muted)", fontSize: 12.5, lineHeight: 1.55 }}>
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--muted-2)",
                  marginBottom: 8,
                }}
              >
                Inspector
              </div>
              <p style={{ margin: 0 }}>
                Select a node on the canvas to edit it. Drag a dataset from the left to add a source
                node. Drag a transform (Join, Filter, Formula, Select, Union, Output) and connect
                them. Joins between two datasets that share an <strong>ontology relationship</strong>{" "}
                auto-suggest keys.
              </p>
            </div>
          )}
        </div>

        {previewOpen ? (
          <div style={{ gridColumn: "2 / 4", minHeight: 0, overflow: "hidden", border: "1px solid var(--line)", borderRadius: 3 }}>
            {validation ? (
              <BottomDrawer title="Pipeline warnings" tabs={["Selection preview", "Preview", "Transformations", "Suggestions", "Pipeline warnings"]} active="Pipeline warnings">
                {[...validation.errors, ...validation.warnings].map((w, i) => <div key={i} className={`badge ${validation.errors.includes(w) ? "badge-danger" : "badge-warning"}`} style={{ margin: 4 }}>{w.code}: {w.message}</div>)}
                {!validation.errors.length && !validation.warnings.length ? <div style={{ color: "var(--muted)" }}>No warnings.</div> : null}
              </BottomDrawer>
            ) : (
              <PreviewPanel
                preview={preview}
                error={previewError}
                loading={previewLoading}
                onRun={runPreview}
                onClose={() => setPreviewOpen(false)}
              />
            )}
          </div>
        ) : null}
      </div>
      {platformResourceId ? <ResourceComments resourceId={platformResourceId} /> : null}
    </div>
  );
}
