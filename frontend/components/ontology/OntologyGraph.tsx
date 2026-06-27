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
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";

type GraphNode = {
  id: string;
  type_name: string;
  dataset_id: string;
  primary_key: string;
  display_name_column: string | null;
  properties: { name: string; column: string; type?: string | null }[];
  description: string | null;
  position: { x?: number; y?: number };
};

type GraphEdge = {
  id: string;
  source: string;
  target: string;
  name: string;
  cardinality: string;
  source_key: string;
  target_key: string;
};

type GraphResponse = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  viewport: Record<string, number>;
};

function ObjectNode({ data, selected }: { data: { node: GraphNode }; selected?: boolean }) {
  const n = data.node;
  return (
    <div
      style={{
        width: 220,
        background: "var(--panel)",
        border: `1px solid ${selected ? "var(--accent)" : "var(--accent-line)"}`,
        borderRadius: 3,
        boxShadow: selected ? "0 0 0 2px var(--accent-soft)" : "0 6px 16px rgba(0,0,0,0.2)",
        color: "var(--text)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "7px 9px",
          borderBottom: "1px solid var(--line-soft)",
          background: "linear-gradient(180deg, rgba(255,255,255,0.02), rgba(0,0,0,0.08))",
        }}
      >
        <span
          aria-hidden
          style={{
            width: 6,
            height: 6,
            borderRadius: 6,
            background: "var(--accent)",
          }}
        />
        <span
          style={{
            fontSize: 9.5,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--muted-2)",
          }}
        >
          Object
        </span>
      </div>
      <div style={{ padding: "8px 10px" }}>
        <div style={{ fontSize: 13, fontWeight: 650 }}>{n.type_name}</div>
        <div
          className="font-mono"
          style={{ fontSize: 10.5, color: "var(--muted)", marginTop: 2 }}
        >
          PK · {n.primary_key}
        </div>
        {n.properties.length > 0 ? (
          <div
            style={{
              marginTop: 6,
              display: "flex",
              flexWrap: "wrap",
              gap: 4,
            }}
          >
            {n.properties.slice(0, 6).map((p) => (
              <span
                key={p.name}
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 10,
                  padding: "1px 5px",
                  background: "var(--bg-2)",
                  border: "1px solid var(--line-soft)",
                  borderRadius: 2,
                  color: "var(--muted)",
                }}
              >
                {p.name}
              </span>
            ))}
            {n.properties.length > 6 ? (
              <span style={{ fontSize: 10, color: "var(--muted-2)" }}>
                +{n.properties.length - 6}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

const NODE_TYPES = { object: ObjectNode };

function layoutDefault(graph: GraphResponse): Record<string, { x: number; y: number }> {
  const out: Record<string, { x: number; y: number }> = {};
  const cols = Math.max(1, Math.ceil(Math.sqrt(graph.nodes.length)));
  graph.nodes.forEach((n, i) => {
    const stored = n.position;
    if (stored && typeof stored.x === "number" && typeof stored.y === "number") {
      out[n.id] = { x: stored.x, y: stored.y };
      return;
    }
    const r = Math.floor(i / cols);
    const c = i % cols;
    out[n.id] = { x: c * 280 + 40, y: r * 200 + 40 };
  });
  return out;
}

function Inner() {
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rfNodes, setRfNodes] = useState<Node[]>([]);
  const [rfEdges, setRfEdges] = useState<Edge[]>([]);
  const idsByType = useRef<Record<string, string>>({});
  const saveTimer = useRef<number | null>(null);

  useEffect(() => {
    apiFetch<GraphResponse>("/ontology/graph")
      .then((g) => {
        setGraph(g);
        const positions = layoutDefault(g);
        idsByType.current = Object.fromEntries(g.nodes.map((n) => [n.type_name, n.id]));
        setRfNodes(
          g.nodes.map((n) => ({
            id: n.id,
            type: "object",
            position: positions[n.id],
            data: { node: n },
          })),
        );
        setRfEdges(
          g.edges.map((e) => ({
            id: e.id,
            source: idsByType.current[e.source] ?? e.source,
            target: idsByType.current[e.target] ?? e.target,
            label: `${e.name} · ${e.cardinality}`,
            labelBgPadding: [4, 2] as [number, number],
            labelBgStyle: { fill: "var(--panel-2)" },
            labelStyle: { fill: "var(--muted)", fontSize: 10, fontFamily: "var(--font-mono)" },
            style: { stroke: "var(--accent)", strokeWidth: 1.5 },
          })),
        );
      })
      .catch((e) => setError(e.message));
  }, []);

  const saveLayout = useCallback(() => {
    if (!graph) return;
    const positions: Record<string, { x: number; y: number }> = {};
    rfNodes.forEach((n) => {
      positions[n.id] = { x: n.position.x, y: n.position.y };
    });
    apiFetch("/ontology/layout", {
      method: "POST",
      body: JSON.stringify({ positions, viewport: {} }),
    }).catch(() => undefined);
  }, [graph, rfNodes]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setRfNodes((cur) => applyNodeChanges(changes, cur));
      // Debounced save.
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(saveLayout, 600) as unknown as number;
    },
    [saveLayout],
  );

  if (error) {
    return (
      <div className="app-card empty-state">
        <div className="empty-state-title" style={{ color: "var(--danger)" }}>
          Failed to load ontology graph
        </div>
        <div className="empty-state-help">{error}</div>
      </div>
    );
  }
  if (!graph) {
    return (
      <div className="app-card empty-state">
        <div className="empty-state-title">Loading ontology…</div>
      </div>
    );
  }
  if (graph.nodes.length === 0) {
    return (
      <div className="app-card empty-state">
        <div className="empty-state-title">No object types yet</div>
        <div className="empty-state-help">Import YAML below to seed the ontology.</div>
      </div>
    );
  }

  return (
    <div
      style={{
        height: 560,
        border: "1px solid var(--line)",
        borderRadius: 3,
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
          nodeColor="#5e8bff"
          style={{ background: "var(--bg-2)", border: "1px solid var(--line)" }}
        />
        <Controls position="bottom-right" />
      </ReactFlow>
    </div>
  );
}

export function OntologyGraph() {
  return (
    <ReactFlowProvider>
      <Inner />
    </ReactFlowProvider>
  );
}
