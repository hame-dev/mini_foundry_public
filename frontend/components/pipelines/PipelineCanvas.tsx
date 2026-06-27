"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";
import type {
  JoinSuggestion,
  NodeType,
  PipelineEdge,
  PipelineNode,
  TargetHandle,
} from "@/lib/pipelines";
import type { Dataset } from "@/lib/types";
import { DRAG_MIME } from "./DatasetPalette";
import { NODE_RENDERERS, type CanvasNodeData } from "./nodes";

export type CanvasGraph = {
  nodes: PipelineNode[];
  edges: PipelineEdge[];
};

type Props = {
  initialNodes: PipelineNode[];
  initialEdges: PipelineEdge[];
  onChange: (graph: CanvasGraph) => void;
  onSelectNode: (nodeId: string | null) => void;
  onSelectEdge: (edgeId: string | null) => void;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  datasets: Dataset[];
};

function rid(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

function toRfNodes(nodes: PipelineNode[], datasetsById: Record<string, Dataset>): Node<CanvasNodeData>[] {
  return nodes.map((n) => {
    let datasetName: string | null = null;
    let datasetSubtitle: string | null = null;
    if (n.node_type === "source") {
      const dsId = (n.config as { dataset_id?: string }).dataset_id;
      const d = dsId ? datasetsById[dsId] : undefined;
      if (d) {
        datasetName = d.name;
        datasetSubtitle = `${d.schema_name}.${d.table_name}`;
      }
    }
    return {
      id: n.id,
      type: n.node_type,
      position: { x: n.position?.x ?? 0, y: n.position?.y ?? 0 },
      data: { config: n.config, datasetName, datasetSubtitle },
    } as Node<CanvasNodeData>;
  });
}

function toRfEdges(edges: PipelineEdge[]): Edge[] {
  return edges.map((e) => ({
    id: e.id,
    source: e.source_node_id,
    target: e.target_node_id,
    targetHandle: e.target_handle,
    type: "default",
    style: { stroke: "var(--accent)", strokeWidth: 1.5 },
  }));
}

function PipelineCanvasInner({
  initialNodes,
  initialEdges,
  onChange,
  onSelectNode,
  onSelectEdge,
  selectedNodeId,
  selectedEdgeId,
  datasets,
}: Props) {
  const datasetsById = useMemo(() => Object.fromEntries(datasets.map((d) => [d.id, d])), [datasets]);

  const [rfNodes, setRfNodes] = useState<Node<CanvasNodeData>[]>(() => toRfNodes(initialNodes, datasetsById));
  const [rfEdges, setRfEdges] = useState<Edge[]>(() => toRfEdges(initialEdges));
  // Keep a parallel map of pipeline-level edge metadata (target_handle).
  const pipelineNodes = useRef<PipelineNode[]>(initialNodes);
  const pipelineEdges = useRef<PipelineEdge[]>(initialEdges);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const rf = useReactFlow();

  const emit = useCallback(() => {
    const graph = { nodes: [...pipelineNodes.current], edges: [...pipelineEdges.current] };
    queueMicrotask(() => onChange(graph));
  }, [onChange]);

  // Recompute RF nodes when datasets or initialNodes change externally.
  useEffect(() => {
    pipelineNodes.current = initialNodes;
    pipelineEdges.current = initialEdges;
    setRfNodes(toRfNodes(pipelineNodes.current, datasetsById));
    setRfEdges(toRfEdges(pipelineEdges.current));
  }, [datasetsById, initialEdges, initialNodes]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setRfNodes((cur) => {
        const next = applyNodeChanges(changes, cur) as Node<CanvasNodeData>[];
        // Persist position changes back to pipelineNodes.
        for (const ch of changes) {
          if (ch.type === "position" && ch.position) {
            const pn = pipelineNodes.current.find((p) => p.id === ch.id);
            if (pn) pn.position = { x: ch.position.x, y: ch.position.y };
          }
          if (ch.type === "remove") {
            pipelineNodes.current = pipelineNodes.current.filter((p) => p.id !== ch.id);
            pipelineEdges.current = pipelineEdges.current.filter(
              (e) => e.source_node_id !== ch.id && e.target_node_id !== ch.id,
            );
          }
        }
        emit();
        return next;
      });
    },
    [emit],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setRfEdges((cur) => {
        const next = applyEdgeChanges(changes, cur);
        for (const ch of changes) {
          if (ch.type === "remove") {
            pipelineEdges.current = pipelineEdges.current.filter((e) => e.id !== ch.id);
          }
        }
        emit();
        return next;
      });
    },
    [emit],
  );

  const addPipelineEdge = useCallback(
    (rfEdge: Edge) => {
      const handle = (rfEdge.targetHandle ?? "in") as TargetHandle;
      const pe: PipelineEdge = {
        id: rfEdge.id,
        source_node_id: rfEdge.source!,
        target_node_id: rfEdge.target!,
        target_handle: handle,
      };
      pipelineEdges.current = [...pipelineEdges.current, pe];
    },
    [],
  );

  // Auto-suggest join keys when two source nodes are connected to a join node.
  const maybeSuggestJoin = useCallback(
    async (joinNodeId: string) => {
      const inbound = pipelineEdges.current.filter((e) => e.target_node_id === joinNodeId);
      const left = inbound.find((e) => e.target_handle === "left");
      const right = inbound.find((e) => e.target_handle === "right");
      if (!left || !right) return;
      const leftSrc = pipelineNodes.current.find((n) => n.id === left.source_node_id);
      const rightSrc = pipelineNodes.current.find((n) => n.id === right.source_node_id);
      if (!leftSrc || !rightSrc) return;
      const leftDs = (leftSrc.config as { dataset_id?: string }).dataset_id;
      const rightDs = (rightSrc.config as { dataset_id?: string }).dataset_id;
      if (!leftDs || !rightDs) return;
      try {
        const res = await apiFetch<{ suggestion: JoinSuggestion | null }>(
          `/pipelines/_suggest/join?left_dataset_id=${leftDs}&right_dataset_id=${rightDs}`,
        );
        if (!res.suggestion) return;
        const target = pipelineNodes.current.find((n) => n.id === joinNodeId);
        if (!target) return;
        target.config = {
          ...target.config,
          join_type: res.suggestion.join_type,
          left_keys: res.suggestion.left_keys,
          right_keys: res.suggestion.right_keys,
          suggested_from_ontology_relationship_id: res.suggestion.relationship_id,
        };
        setRfNodes((cur) =>
          cur.map((n) =>
            n.id === joinNodeId
              ? { ...n, data: { ...(n.data as CanvasNodeData), config: target.config, ontologySuggested: true } }
              : n,
          ),
        );
        emit();
      } catch {
        // best-effort; no toast
      }
    },
    [emit],
  );

  const onConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target) return;
      const id = rid("e");
      const rfEdge: Edge = {
        id,
        source: conn.source,
        target: conn.target,
        sourceHandle: conn.sourceHandle ?? undefined,
        targetHandle: conn.targetHandle ?? "in",
        style: { stroke: "var(--accent)", strokeWidth: 1.5 },
      };
      setRfEdges((es) => addEdge(rfEdge, es));
      addPipelineEdge(rfEdge);
      emit();
      // If the target is a join, try the ontology suggestion path.
      const targetNode = pipelineNodes.current.find((n) => n.id === conn.target);
      if (targetNode?.node_type === "join") {
        void maybeSuggestJoin(conn.target!);
      }
    },
    [addPipelineEdge, emit, maybeSuggestJoin],
  );

  // Drag from palette → drop creates a source node.
  const onDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    if (Array.from(e.dataTransfer.types).includes(DRAG_MIME)) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    }
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData(DRAG_MIME);
      if (!raw) return;
      let payload: { kind: string; dataset_id?: string; node_type?: NodeType };
      try {
        payload = JSON.parse(raw);
      } catch {
        return;
      }
      const bounds = wrapperRef.current?.getBoundingClientRect();
      const pos = rf.screenToFlowPosition({
        x: e.clientX - (bounds?.left ?? 0),
        y: e.clientY - (bounds?.top ?? 0),
      });
      if (payload.kind === "dataset" && payload.dataset_id) {
        const newId = rid("n");
        const pn: PipelineNode = {
          id: newId,
          node_type: "source",
          position: pos,
          config: { dataset_id: payload.dataset_id },
        };
        pipelineNodes.current = [...pipelineNodes.current, pn];
        setRfNodes((cur) => [...cur, ...toRfNodes([pn], datasetsById)]);
        emit();
      } else if (payload.kind === "node_type" && payload.node_type) {
        const newId = rid("n");
        const pn: PipelineNode = {
          id: newId,
          node_type: payload.node_type,
          position: pos,
          config: defaultConfigFor(payload.node_type),
        };
        pipelineNodes.current = [...pipelineNodes.current, pn];
        setRfNodes((cur) => [...cur, ...toRfNodes([pn], datasetsById)]);
        emit();
      }
    },
    [datasetsById, emit, rf],
  );

  const onSelChange = useCallback(
    (params: { nodes: Node[]; edges: Edge[] }) => {
      const nextNode = params.nodes[0]?.id ?? null;
      const nextEdge = params.edges[0]?.id ?? null;
      queueMicrotask(() => {
        onSelectNode(nextNode);
        onSelectEdge(nextEdge);
      });
    },
    [onSelectEdge, onSelectNode],
  );

  // Reflect external selection (e.g. clicking in inspector) back to RF.
  useEffect(() => {
    setRfNodes((cur) =>
      cur.map((n) => ({ ...n, selected: n.id === selectedNodeId })),
    );
  }, [selectedNodeId]);
  useEffect(() => {
    setRfEdges((cur) =>
      cur.map((e) => ({ ...e, selected: e.id === selectedEdgeId })),
    );
  }, [selectedEdgeId]);

  return (
    <div
      ref={wrapperRef}
      onDragOver={onDragOver}
      onDrop={onDrop}
      style={{ width: "100%", height: "100%", background: "var(--bg)" }}
    >
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onSelectionChange={onSelChange}
        nodeTypes={NODE_RENDERERS}
        fitView
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ style: { stroke: "var(--accent)", strokeWidth: 1.5 } }}
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="#1f2731" />
        <MiniMap
          pannable
          zoomable
          maskColor="rgba(10,13,18,0.72)"
          nodeColor={(n) => {
            if (n.type === "source") return "#5e8bff";
            if (n.type === "join") return "#3ec6c0";
            if (n.type === "output") return "#4cd496";
            return "#3a4658";
          }}
          style={{ background: "var(--bg-2)", border: "1px solid var(--line)" }}
        />
        <Controls
          position="bottom-right"
          style={{
            background: "var(--bg-2)",
            border: "1px solid var(--line)",
            borderRadius: 3,
          }}
        />
      </ReactFlow>
    </div>
  );
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

export function PipelineCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <PipelineCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
