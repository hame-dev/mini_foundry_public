"use client";

import type { NodeProps, NodeTypes } from "@xyflow/react";
import { NodeCard } from "./NodeCard";

export type CanvasNodeData = {
  config: Record<string, unknown>;
  datasetName?: string | null;
  datasetSubtitle?: string | null;
  ontologySuggested?: boolean;
};

function SourceNode({ data, selected }: NodeProps) {
  const d = data as CanvasNodeData;
  const cfg = d.config ?? {};
  const hasDs = Boolean(d.datasetName);
  return (
    <NodeCard
      nodeType="source"
      variant="source"
      selected={selected}
      title={d.datasetName || "Pick a dataset"}
      subtitle={d.datasetSubtitle ?? null}
      badge={
        !hasDs ? (
          <span className="badge badge-warning">Empty</span>
        ) : (
          <span className="badge badge-accent">DS</span>
        )
      }
      inputs={[]}
    />
  );
}

function JoinNode({ data, selected }: NodeProps) {
  const d = data as CanvasNodeData;
  const cfg = (d.config ?? {}) as { join_type?: string; left_keys?: string[]; right_keys?: string[] };
  const keys = (cfg.left_keys || []).map((lk, i) => `${lk} = ${(cfg.right_keys || [])[i] || "?"}`).join(", ");
  return (
    <NodeCard
      nodeType="join"
      variant="join"
      selected={selected}
      title={(cfg.join_type || "inner").toUpperCase() + " JOIN"}
      subtitle={keys || "Configure join keys →"}
      badge={d.ontologySuggested ? <span className="badge badge-accent">Ontology</span> : null}
      inputs={[
        { id: "left", label: "L" },
        { id: "right", label: "R" },
      ]}
    />
  );
}

function UnionNode({ data, selected }: NodeProps) {
  const d = data as CanvasNodeData;
  const cfg = (d.config ?? {}) as { distinct?: boolean };
  return (
    <NodeCard
      nodeType="union"
      selected={selected}
      title={cfg.distinct ? "UNION (distinct)" : "UNION ALL"}
      subtitle="Stacks inputs with the same schema"
      inputs={[
        { id: "in", label: "A" },
        { id: "in_b", label: "B" },
      ]}
    />
  );
}

function FilterNode({ data, selected }: NodeProps) {
  const d = data as CanvasNodeData;
  const where = ((d.config ?? {}) as { where?: string }).where || "";
  return (
    <NodeCard
      nodeType="filter"
      selected={selected}
      title="WHERE"
      subtitle={where ? where.slice(0, 60) : "No filter set"}
      inputs={[{ id: "in" }]}
    />
  );
}

function FormulaNode({ data, selected }: NodeProps) {
  const d = data as CanvasNodeData;
  const cols = ((d.config ?? {}) as { columns?: { name: string; expr: string }[] }).columns || [];
  return (
    <NodeCard
      nodeType="formula"
      selected={selected}
      title={cols.length > 0 ? `${cols.length} formula${cols.length === 1 ? "" : "s"}` : "No formulas"}
      subtitle={cols.length > 0 ? cols.map((c) => c.name).join(", ") : "Add computed columns →"}
      inputs={[{ id: "in" }]}
    />
  );
}

function SelectNode({ data, selected }: NodeProps) {
  const d = data as CanvasNodeData;
  const cfg = (d.config ?? {}) as { columns?: string[] };
  const cols = cfg.columns || [];
  return (
    <NodeCard
      nodeType="select"
      selected={selected}
      title={cols.length > 0 ? `${cols.length} columns` : "All columns"}
      subtitle={cols.length > 0 ? cols.slice(0, 4).join(", ") + (cols.length > 4 ? ` +${cols.length - 4}` : "") : "Passthrough"}
      inputs={[{ id: "in" }]}
    />
  );
}

function OutputNode({ data, selected }: NodeProps) {
  const d = data as CanvasNodeData;
  const cfg = (d.config ?? {}) as { name?: string; description?: string };
  return (
    <NodeCard
      nodeType="output"
      variant="output"
      selected={selected}
      title={cfg.name || "Output dataset"}
      subtitle={cfg.description ?? "Materializes as a Postgres VIEW"}
      badge={<span className="badge badge-success">View</span>}
      inputs={[{ id: "in" }]}
      outputs={[]}
    />
  );
}

function TrainedModelNode({ data, selected }: NodeProps) {
  const d = data as CanvasNodeData;
  const cfg = (d.config ?? {}) as { model_id?: string; version_id?: string; prediction_column?: string };
  return (
    <NodeCard
      nodeType="trained_model"
      variant="join"
      selected={selected}
      title={cfg.model_id ? "Model inference" : "Pick model"}
      subtitle={cfg.prediction_column ? `adds ${cfg.prediction_column}` : "Appends prediction column"}
      badge={<span className="badge badge-accent">ML</span>}
      inputs={[{ id: "in" }]}
    />
  );
}

export const NODE_RENDERERS: NodeTypes = {
  source: SourceNode,
  join: JoinNode,
  union: UnionNode,
  filter: FilterNode,
  formula: FormulaNode,
  select: SelectNode,
  trained_model: TrainedModelNode,
  output: OutputNode,
};
