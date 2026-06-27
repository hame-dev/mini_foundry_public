import { apiFetch } from "@/lib/api";

export const FILTER_OPERATORS = [
  "eq",
  "ne",
  "gt",
  "gte",
  "lt",
  "lte",
  "like",
  "ilike",
  "in",
  "is_null",
  "not_null",
] as const;

export type FilterOperator = (typeof FILTER_OPERATORS)[number];

export type FilterPredicate = {
  column: string;
  op: FilterOperator;
  value?: unknown;
};

export type ObjectSet = {
  id: string;
  name: string;
  object_type: string;
  filters: FilterPredicate[];
  description: string | null;
  owner_id: string | null;
};

export type OntologyFunction = {
  id: string;
  object_type: string;
  name: string;
  expression: string;
  return_type: string | null;
  description: string | null;
};

export type ObjectSetResultRow = {
  id: unknown;
  display_name: string | null;
  properties: Record<string, unknown>;
  functions: Record<string, unknown>;
};

export type ObjectSetResult = {
  object_type: string;
  objects: ObjectSetResultRow[];
  row_count: number;
  columns: string[];
  dataset_versions: unknown[];
};

export type QueryOptions = {
  limit?: number;
  offset?: number;
  sort_by?: string | null;
  sort_dir?: "asc" | "desc";
};

// --- Object sets -----------------------------------------------------------

export function listObjectSets(objectType?: string): Promise<ObjectSet[]> {
  const q = objectType ? `?object_type=${encodeURIComponent(objectType)}` : "";
  return apiFetch<ObjectSet[]>(`/ontology/object-sets${q}`);
}

export function getObjectSet(id: string): Promise<ObjectSet> {
  return apiFetch<ObjectSet>(`/ontology/object-sets/${id}`);
}

export function createObjectSet(body: {
  name: string;
  object_type: string;
  filters: FilterPredicate[];
  description?: string | null;
}): Promise<ObjectSet> {
  return apiFetch<ObjectSet>("/ontology/object-sets", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteObjectSet(id: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/ontology/object-sets/${id}`, { method: "DELETE" });
}

export function queryObjectSet(id: string, opts: QueryOptions = {}): Promise<ObjectSetResult> {
  return apiFetch<ObjectSetResult>(`/ontology/object-sets/${id}/query`, {
    method: "POST",
    body: JSON.stringify(opts),
  });
}

// Ad-hoc filter (no saved set).
export function queryObjects(
  objectType: string,
  filters: FilterPredicate[],
  opts: QueryOptions = {},
): Promise<ObjectSetResult> {
  return apiFetch<ObjectSetResult>(`/objects/${objectType}/query`, {
    method: "POST",
    body: JSON.stringify({ filters, ...opts }),
  });
}

// --- Functions on objects --------------------------------------------------

export function listFunctions(objectType: string): Promise<OntologyFunction[]> {
  return apiFetch<OntologyFunction[]>(`/ontology/objects/${objectType}/functions`);
}

export function createFunction(
  objectType: string,
  body: { name: string; expression: string; return_type?: string | null; description?: string | null },
): Promise<OntologyFunction> {
  return apiFetch<OntologyFunction>(`/admin/ontology/objects/${objectType}/functions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deleteFunction(functionId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/admin/ontology/functions/${functionId}`, { method: "DELETE" });
}
