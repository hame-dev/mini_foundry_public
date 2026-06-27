export type WorkspaceItemType =
  | "folder"
  | "sql"
  | "notebook"
  | "code_repository"
  | "dashboard"
  | "pipeline"
  | "model"
  | "ontology"
  | "dataset_link";

export type WorkspaceItem = {
  id: string;
  name: string;
  item_type: WorkspaceItemType;
  parent_id: string | null;
  resource_type: string | null;
  resource_id: string | null;
  owner_id: string | null;
  href: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkspacePermission = {
  id: string;
  item_id: string;
  subject_type: "user" | "role" | "everyone";
  subject_id: string | null;
  can_view: boolean;
  can_edit: boolean;
  can_run: boolean;
  can_share: boolean;
  can_manage: boolean;
};

export const WORKSPACE_LABELS: Record<WorkspaceItemType, string> = {
  folder: "Folder",
  sql: "SQL",
  notebook: "Notebook",
  code_repository: "Code repository",
  dashboard: "Dashboard",
  pipeline: "Pipeline",
  model: "Model",
  ontology: "Ontology",
  dataset_link: "Dataset",
};
