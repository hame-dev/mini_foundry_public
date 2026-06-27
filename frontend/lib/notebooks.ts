// Mirrors backend/app/notebooks/models.py + router schemas.

export type CellType = "markdown" | "sql" | "python" | "ai_prompt";

export const CELL_LABELS: Record<CellType, string> = {
  markdown: "Markdown",
  sql: "SQL",
  python: "Python",
  ai_prompt: "AI prompt",
};

export type CellOutput = {
  // markdown
  markdown?: string;
  // sql
  columns?: string[];
  rows?: Record<string, unknown>[];
  // python sandbox
  stdout?: string;
  stderr?: string;
  error?: string | null;
  images_b64?: string[];
  dataframes?: Array<{ name: string; columns: string[]; rows: Record<string, unknown>[]; total_rows: number }>;
  // ai_prompt
  generated_code?: string;
  explanation?: string;
};

export type NotebookCell = {
  id: string;
  notebook_id: string;
  position: number;
  cell_type: CellType;
  source: string;
  dataset_ids: string[];
  last_output: CellOutput | null;
  last_run_at: string | null;
  last_status: string | null;
  last_job_id: string | null;
};

export type NotebookSummary = {
  id: string;
  title: string;
  description: string | null;
  owner_id: string | null;
  ai_policy: string;
  notebook_kind: "sql" | "python";
  requirements: string[] | null;
  kernel_name: string | null;
  workspace_metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type NotebookDetail = NotebookSummary & {
  cells: NotebookCell[];
};
