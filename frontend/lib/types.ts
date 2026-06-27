export type User = {
  id: string;
  email: string;
  name: string | null;
  roles: string[];
};

export type Dataset = {
  id: string;
  name: string;
  description: string | null;
  source_id: string | null;
  schema_name: string;
  table_name: string;
  row_count: number | null;
  ai_policy: string;
  derived_from_pipeline_id?: string | null;
  created_at: string;
};

export type Column = {
  name: string;
  data_type: string | null;
  description: string | null;
  sample_values: unknown[] | null;
};

export type DatasetDetail = Dataset & {
  columns: Column[];
  profile: Record<string, unknown> | null;
  resource_id?: string | null;
  security_markings?: string[];
  stewards?: string[];
  tags?: string[];
  glossary_terms?: string[];
};

export type AiSqlResponse = {
  sql: string;
  explanation: string;
  confidence: number;
  provider: string;
  model: string;
  dataset_ids: string[];
};

export type SqlRunResponse = {
  cached: boolean;
  phase?: string;
  resolved_sql?: string;
  query_id?: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
};

export type AuditLog = {
  id: string;
  user_id: string | null;
  event_type: string;
  resource_type: string | null;
  resource_id: string | null;
  provider: string | null;
  input_summary: Record<string, unknown> | null;
  output_summary: Record<string, unknown> | null;
  created_at: string;
};

export type ResourceActivity = {
  id: string;
  resource_type: string;
  resource_id: string;
  title: string;
  path: string | null;
  favorite: boolean;
  metadata: Record<string, unknown> | null;
  last_viewed_at: string;
  created_at: string;
};

export type CodeRepositorySummary = {
  id: string;
  name: string;
  description: string | null;
  repo_type: string;
  default_branch: string;
  owner_id: string | null;
  created_at: string;
  updated_at: string;
};

export type CodeRepositoryFile = {
  path: string;
  size: number;
  language: string;
};

export type WidgetDefinition = {
  id: string;
  label: string;
  category: string;
  description: string;
};

export type AISettings = {
  provider: string;
  model: string | null;
  api_base: string | null;
  api_key_configured: boolean;
  policy: string;
  extra: Record<string, unknown>;
};
