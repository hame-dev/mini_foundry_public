import { apiFetch } from "./api";

export type LineageNode = {
  id: string;
  resource_type: string;
  object_id: string | null;
  name: string;
  project_id: string | null;
};

export type LineageEdge = {
  id: string;
  source_resource_id: string | null;
  source_version_id: string | null;
  target_resource_id: string | null;
  target_version_id: string | null;
  edge_type: string;
  metadata: Record<string, unknown>;
  hidden_source: boolean;
  hidden_target: boolean;
  created_at: string;
};

export type ResourceLineage = {
  resource_id: string;
  direction: "upstream" | "downstream" | "both";
  depth: number;
  branch_name: string | null;
  nodes: LineageNode[];
  edges: LineageEdge[];
  hidden_nodes: { count: number };
};

export type ResourceImpact = {
  resource_id: string;
  depth: number;
  columns: string[];
  affected: LineageNode[];
  by_type: Record<string, number>;
  edge_count: number;
  hidden_nodes: { count: number };
};

export function getResourceLineage(resourceId: string, params: {
  direction?: "upstream" | "downstream" | "both";
  depth?: number;
  branch_name?: string;
  include_columns?: boolean;
} = {}): Promise<ResourceLineage> {
  const qs = new URLSearchParams();
  if (params.direction) qs.set("direction", params.direction);
  if (params.depth) qs.set("depth", String(params.depth));
  if (params.branch_name) qs.set("branch_name", params.branch_name);
  if (params.include_columns) qs.set("include_columns", "true");
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiFetch<ResourceLineage>(`/platform/resources/${resourceId}/lineage${suffix}`);
}

export function getResourceImpact(resourceId: string, params: { depth?: number; columns?: string } = {}): Promise<ResourceImpact> {
  const qs = new URLSearchParams();
  if (params.depth) qs.set("depth", String(params.depth));
  if (params.columns) qs.set("columns", params.columns);
  const suffix = qs.toString() ? `?${qs}` : "";
  return apiFetch<ResourceImpact>(`/platform/resources/${resourceId}/impact${suffix}`);
}
