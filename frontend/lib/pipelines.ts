// TS shapes mirroring backend/app/pipelines/schemas.py.

export type NodeType =
  | "source"
  | "join"
  | "union"
  | "filter"
  | "formula"
  | "select"
  | "trained_model"
  | "output";

export type JoinType = "inner" | "left" | "right" | "full";
export type TargetHandle = "left" | "right" | "in";

export type Position = { x?: number; y?: number };

// Per-node config (loose: backend tolerates extra keys)
export interface SourceConfig {
  dataset_id: string;
}
export interface JoinConfig {
  join_type?: JoinType;
  left_keys?: string[];
  right_keys?: string[];
  suggested_from_ontology_relationship_id?: string | null;
}
export interface UnionConfig {
  distinct?: boolean;
}
export interface FilterConfig {
  where?: string;
}
export interface FormulaColumn {
  name: string;
  expr: string;
}
export interface FormulaConfig {
  columns?: FormulaColumn[];
}
export interface SelectConfig {
  columns?: string[];
  rename?: Record<string, string>;
}
export interface OutputConfig {
  name: string;
  description?: string | null;
  materialize?: "view" | "table" | "parquet";
}

export interface TrainedModelConfig {
  model_id?: string;
  version_id?: string;
  prediction_column?: string;
}

export type PipelineNode = {
  id: string;
  node_type: NodeType;
  position: Position;
  config: Record<string, unknown>;
};

export type PipelineEdge = {
  id: string;
  source_node_id: string;
  target_node_id: string;
  target_handle: TargetHandle;
};

export type PipelineSummary = {
  id: string;
  name: string;
  description: string | null;
  owner_id: string | null;
  ai_policy: string;
  output_dataset_id: string | null;
  materialization_type: "view" | "table" | "parquet";
  materialized_at: string | null;
  materialized_rows: number | null;
  last_run_at: string | null;
  last_run_status: string | null;
  created_at: string;
  updated_at: string;
};

export type PipelineDetail = PipelineSummary & {
  graph: Record<string, unknown>;
  nodes: PipelineNode[];
  edges: PipelineEdge[];
  last_run_error: string | null;
};

export type PreviewOut = {
  columns: string[];
  rows: Record<string, unknown>[];
  sql: string;
};

export type RunOut = {
  status: "ok" | "error" | "queued";
  output_dataset_id?: string | null;
  output_saved_query_id?: string | null;
  view_name?: string | null;
  columns?: string[];
  error?: string | null;
  job_id?: string | null;
  materialization_type?: "view" | "table" | "parquet";
  materialized_rows?: number | null;
  build_run_id?: string | null;
  output_dataset_version_id?: string | null;
};

export type JoinSuggestion = {
  relationship_id: string;
  relationship_name: string;
  cardinality: string;
  join_type: JoinType;
  left_keys: string[];
  right_keys: string[];
  source_type: string;
  target_type: string;
};

export const NODE_LABELS: Record<NodeType, string> = {
  source: "Source",
  join: "Join",
  union: "Union",
  filter: "Filter",
  formula: "Formula",
  select: "Select",
  trained_model: "Trained model",
  output: "Output",
};

export const NODE_DESCRIPTIONS: Record<NodeType, string> = {
  source: "A dataset from the catalog.",
  join: "Combine two inputs on matching keys.",
  union: "Stack two or more inputs with the same schema.",
  filter: "Keep rows matching a SQL boolean expression.",
  formula: "Add computed columns (sum, +, *, case-when…).",
  select: "Pick columns, rename, reorder.",
  trained_model: "Run a trained model and append prediction columns.",
  output: "Materialize this graph as a derived dataset.",
};
