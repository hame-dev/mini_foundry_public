// Mirrors backend/app/dashboards/registry.py. Keep in sync.

export type BindingType = "sql_query" | "dataset" | "static" | "saved_query";

export type SqlQueryBinding = {
  type: "sql_query";
  sql: string;
  dataset_ids: string[];
  params?: string[];
};

export type DatasetBinding = {
  type: "dataset";
  dataset_id: string;
  group_by?: string[];
  metrics?: Array<{ column: string; aggregation: "count" | "sum" | "avg" | "min" | "max"; alias: string }>;
  where?: string;
  params?: string[];
};

export type StaticBinding = {
  type: "static";
  rows: Record<string, unknown>[];
};

export type SavedQueryBinding = {
  type: "saved_query";
  id: string;
  params?: string[];
};

export type Binding = SqlQueryBinding | DatasetBinding | StaticBinding | SavedQueryBinding;

export type ComponentType =
  | "metric_card"
  | "table"
  | "line_chart"
  | "bar_chart"
  | "pie_chart"
  | "markdown"
  | "filter_date"
  | "filter_select"
  | "object_table"
  | "button_group"
  | "filter_list"
  | "chart_xy"
  | "map"
  | "data_table";

export type ComponentPosition = { x: number; y: number; w: number; h: number };

import type { DashboardAction } from "./actions";

export type DashboardComponent = {
  id: string;
  component_type: ComponentType;
  title?: string | null;
  position: ComponentPosition;
  config: Record<string, unknown>;
  data_binding: Binding | null;
  refresh?: { mode: "cached" | "live" | "manual"; ttl_seconds?: number } | null;
  actions?: DashboardAction[];
};

export type DashboardFilter = {
  id: string;
  type: "date_range" | "select" | "multi_select" | "search";
  target_fields: string[];
  label?: string;
};

export type DashboardLayout = {
  version: 1;
  components: DashboardComponent[];
  filters: DashboardFilter[];
};

export type DashboardSummary = {
  id: string;
  title: string;
  description: string | null;
  owner_id: string | null;
  dashboard_kind: "contour" | "workshop" | "quiver";
  published_version: number;
  published_at: string | null;
  draft_updated_at: string | null;
  created_at: string;
  updated_at: string;
};

export type DashboardDetail = DashboardSummary & {
  layout: DashboardLayout;
  components: DashboardComponent[];
  is_draft_view: boolean;
};

export type SavedQuery = {
  id: string;
  name: string;
  sql: string;
  dataset_ids: string[];
  owner_id: string | null;
  created_at: string;
};

export type ComponentRender = {
  id: string;
  status?: "ok" | "cached" | "error";
  columns?: string[];
  rows?: Record<string, unknown>[];
  error?: string;
  cached?: boolean;
  elapsed_ms?: number;
};

export type RenderOut = {
  dashboard_id: string;
  components: ComponentRender[];
  elapsed_ms?: number;
};

export const COMPONENT_DEFAULTS: Record<ComponentType, { config: Record<string, unknown>; binding: Binding | null; position: ComponentPosition }> = {
  metric_card: {
    config: { value_column: "value", format: "number" },
    binding: { type: "sql_query", sql: "SELECT COUNT(*) AS value FROM information_schema.tables", dataset_ids: [] },
    position: { x: 0, y: 0, w: 3, h: 2 },
  },
  table: {
    config: {},
    binding: { type: "sql_query", sql: "SELECT 1 AS x", dataset_ids: [] },
    position: { x: 0, y: 0, w: 6, h: 4 },
  },
  line_chart: {
    config: { x: "x", y: "y" },
    binding: { type: "sql_query", sql: "SELECT 1 AS x, 1 AS y", dataset_ids: [] },
    position: { x: 0, y: 0, w: 6, h: 4 },
  },
  bar_chart: {
    config: { x: "x", y: "y" },
    binding: { type: "sql_query", sql: "SELECT 'a' AS x, 1 AS y", dataset_ids: [] },
    position: { x: 0, y: 0, w: 6, h: 4 },
  },
  pie_chart: {
    config: { label: "label", value: "value" },
    binding: { type: "sql_query", sql: "SELECT 'a' AS label, 1 AS value", dataset_ids: [] },
    position: { x: 0, y: 0, w: 4, h: 4 },
  },
  markdown: {
    config: { text: "## Notes\n\nEdit me." },
    binding: { type: "static", rows: [] },
    position: { x: 0, y: 0, w: 6, h: 2 },
  },
  filter_date: {
    config: { target_fields: ["order_date"], default_range_days: 30 },
    binding: { type: "static", rows: [] },
    position: { x: 0, y: 0, w: 4, h: 1 },
  },
  filter_select: {
    config: { target_field: "status", value_column: "status", multi: false },
    binding: { type: "sql_query", sql: "SELECT DISTINCT status FROM staging_orders", dataset_ids: [] },
    position: { x: 0, y: 0, w: 3, h: 1 },
  },
  object_table: {
    config: { object_type: "Customer" },
    binding: { type: "static", rows: [] },
    position: { x: 0, y: 0, w: 6, h: 4 },
  },
  button_group: {
    config: { buttons: [{ label: "Approve", action: "approve" }] },
    binding: { type: "static", rows: [] },
    position: { x: 0, y: 0, w: 3, h: 1 },
  },
  filter_list: {
    config: { target_field: "status" },
    binding: { type: "static", rows: [] },
    position: { x: 0, y: 0, w: 3, h: 3 },
  },
  chart_xy: {
    config: { x: "x", y: "y", mark: "bar" },
    binding: { type: "sql_query", sql: "SELECT 'a' AS x, 1 AS y", dataset_ids: [] },
    position: { x: 0, y: 0, w: 6, h: 4 },
  },
  map: {
    config: { latitude: "latitude", longitude: "longitude" },
    binding: { type: "static", rows: [] },
    position: { x: 0, y: 0, w: 6, h: 4 },
  },
  data_table: {
    config: {},
    binding: { type: "sql_query", sql: "SELECT 1 AS x", dataset_ids: [] },
    position: { x: 0, y: 0, w: 6, h: 4 },
  },
};

export const COMPONENT_LABELS: Record<ComponentType, string> = {
  metric_card: "Metric card",
  table: "Table",
  line_chart: "Line chart",
  bar_chart: "Bar chart",
  pie_chart: "Pie chart",
  markdown: "Markdown",
  filter_date: "Date filter",
  filter_select: "Select filter",
  object_table: "Object table",
  button_group: "Button group",
  filter_list: "Filter list",
  chart_xy: "Chart: XY",
  map: "Map",
  data_table: "Data table",
};
