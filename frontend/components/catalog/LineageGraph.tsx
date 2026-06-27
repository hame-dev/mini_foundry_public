"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeChange,
  applyNodeChanges,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";

type BackendNode = {
  id: string;
  type: string;
  name: string;
  row_count: number | null;
  description: string | null;
};

type BackendEdge = {
  id: string;
  source: string;
  target: string;
};

type LineageResponse = {
  nodes: BackendNode[];
  edges: BackendEdge[];
};

function DatasetNode({ data, selected }: { data: { node: BackendNode }; selected?: boolean }) {
  const n = data.node;
  return (
    <div
      style={{
        width: 220,
        background: "var(--panel)",
        border: `1px solid ${selected ? "var(--accent)" : "var(--accent-line)"}`,
        borderRadius: 4,
        boxShadow: selected ? "0 0 0 2px var(--accent-soft)" : "0 6px 16px rgba(0,0,0,0.15)",
        color: "var(--text)",
        padding: "10px",
        position: "relative",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: "var(--accent)" }} />
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <span aria-hidden>📊</span>
        <span
          style={{
            fontSize: 9.5,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--muted-2)",
          }}
        >
          Dataset
        </span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 650, color: "var(--text)" }}>{n.name}</div>
      <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
        {n.row_count !== null ? `${n.row_count.toLocaleString()} rows` : "— rows"}
      </div>
      <div style={{ marginTop: 8, fontSize: 11 }}>
        <a
          href={`/catalog/${n.id}`}
          style={{
            color: "var(--accent)",
            textDecoration: "none",
            fontWeight: 500,
          }}
        >
          View Catalog →
        </a>
      </div>
      <Handle type="source" position={Position.Right} style={{ background: "var(--accent)" }} />
    </div>
  );
}

function PipelineNode({ data, selected }: { data: { node: BackendNode }; selected?: boolean }) {
  const n = data.node;
  return (
    <div
      style={{
        width: 220,
        background: "var(--panel)",
        border: `1px solid ${selected ? "var(--accent)" : "var(--accent-line)"}`,
        borderRadius: 4,
        boxShadow: selected ? "0 0 0 2px var(--accent-soft)" : "0 6px 16px rgba(0,0,0,0.15)",
        color: "var(--text)",
        padding: "10px",
        position: "relative",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: "var(--accent)" }} />
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <span aria-hidden>⚙️</span>
        <span
          style={{
            fontSize: 9.5,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--muted-2)",
          }}
        >
          Pipeline
        </span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 650, color: "var(--text)" }}>{n.name}</div>
      {n.description && (
        <div
          style={{
            fontSize: 11,
            color: "var(--muted)",
            marginTop: 2,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {n.description}
        </div>
      )}
      <div style={{ marginTop: 8, fontSize: 11 }}>
        <a
          href={`/pipelines/${n.id}`}
          style={{
            color: "var(--accent)",
            textDecoration: "none",
            fontWeight: 500,
          }}
        >
          Open Canvas →
        </a>
      </div>
      <Handle type="source" position={Position.Right} style={{ background: "var(--accent)" }} />
    </div>
  );
}

const NODE_TYPES = {
  dataset: DatasetNode,
  pipeline: PipelineNode,
};

function layoutLineage(graph: LineageResponse): Record<string, { x: number; y: number }> {
  const out: Record<string, { x: number; y: number }> = {};
  
  // Basic topological layout based on connection flow:
  // Find source datasets (no incoming edges), output datasets (no outgoing edges), and pipelines.
  // Group nodes by levels.
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  
  graph.edges.forEach((e) => {
    incoming.set(e.target, [...(incoming.get(e.target) || []), e.source]);
    outgoing.set(e.source, [...(outgoing.get(e.source) || []), e.target]);
  });

  const levelMap = new Map<string, number>();
  
  // Assign levels
  const getLevel = (id: string, visited = new Set<string>()): number => {
    if (levelMap.has(id)) return levelMap.get(id)!;
    if (visited.has(id)) return 0; // handle cycles
    visited.add(id);

    const parents = incoming.get(id) || [];
    if (parents.length === 0) {
      levelMap.set(id, 0);
      return 0;
    }

    let maxParentLevel = 0;
    parents.forEach((p) => {
      maxParentLevel = Math.max(maxParentLevel, getLevel(p, visited));
    });

    const level = maxParentLevel + 1;
    levelMap.set(id, level);
    return level;
  };

  graph.nodes.forEach((n) => getLevel(n.id));

  // Count nodes per level to position vertically
  const levelCounts: Record<number, number> = {};
  const levelIndices: Record<number, number> = {};
  
  graph.nodes.forEach((n) => {
    const lvl = levelMap.get(n.id) || 0;
    levelCounts[lvl] = (levelCounts[lvl] || 0) + 1;
  });

  graph.nodes.forEach((n) => {
    const lvl = levelMap.get(n.id) || 0;
    const count = levelCounts[lvl];
    const index = levelIndices[lvl] || 0;
    levelIndices[lvl] = index + 1;

    // Center layout vertically
    const x = lvl * 320 + 60;
    const y = (index - (count - 1) / 2) * 160 + 200;
    out[n.id] = { x, y };
  });

  return out;
}

function Inner() {
  const [lineage, setLineage] = useState<LineageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rfNodes, setRfNodes] = useState<Node[]>([]);
  const [rfEdges, setRfEdges] = useState<Edge[]>([]);

  useEffect(() => {
    apiFetch<LineageResponse>("/catalog/lineage")
      .then((l) => {
        setLineage(l);
        const positions = layoutLineage(l);
        setRfNodes(
          l.nodes.map((n) => ({
            id: n.id,
            type: n.type,
            position: positions[n.id] || { x: 0, y: 0 },
            data: { node: n },
          })),
        );
        setRfEdges(
          l.edges.map((e) => ({
            id: e.id,
            source: e.source,
            target: e.target,
            style: { stroke: "var(--accent)", strokeWidth: 1.5 },
          })),
        );
      })
      .catch((e) => setError(e.message));
  }, []);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setRfNodes((cur) => applyNodeChanges(changes, cur));
  }, []);

  if (error) {
    return (
      <div className="app-card empty-state">
        <div className="empty-state-title" style={{ color: "var(--danger)" }}>
          Failed to load lineage graph
        </div>
        <div className="empty-state-help">{error}</div>
      </div>
    );
  }

  if (!lineage) {
    return (
      <div className="app-card empty-state">
        <div className="empty-state-title">Loading lineage graph…</div>
      </div>
    );
  }

  if (lineage.nodes.length === 0) {
    return (
      <div className="app-card empty-state">
        <div className="empty-state-title">No lineage data available</div>
        <div className="empty-state-help">
          Create datasets and build pipelines to visualize data flow and dependencies.
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        height: 640,
        border: "1px solid var(--line)",
        borderRadius: 4,
        background: "var(--bg-2)",
        overflow: "hidden",
      }}
    >
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        onNodesChange={onNodesChange}
        nodeTypes={NODE_TYPES}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#1f2731" />
        <MiniMap
          pannable
          zoomable
          maskColor="rgba(10,13,18,0.72)"
          nodeColor={(node) => (node.type === "dataset" ? "#5e8bff" : "#10b981")}
          style={{ background: "var(--bg-2)", border: "1px solid var(--line)" }}
        />
        <Controls position="bottom-right" />
      </ReactFlow>
    </div>
  );
}

export function LineageGraph() {
  return (
    <ReactFlowProvider>
      <Inner />
    </ReactFlowProvider>
  );
}
