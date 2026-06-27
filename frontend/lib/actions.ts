import { apiFetch } from "./api";

// Mirrors backend/app/dashboards/validation.py::ACTION_TYPES + ACTION_EVENTS.

export type ActionEvent = "on_row_click" | "on_click" | "on_cell_click";

export type OpenObjectAction = {
  event: ActionEvent;
  type: "open_object";
  object_type: string;
  id_field: string;
};

export type FilterAction = {
  event: ActionEvent;
  type: "filter";
  filter_id: string;
  source_field?: string;
};

export type NavigateAction = {
  event: ActionEvent;
  type: "navigate";
  to: string;
};

export type RunWorkflowAction = {
  event: ActionEvent;
  type: "run_workflow";
  action_name: string;
};

export type DashboardAction = OpenObjectAction | FilterAction | NavigateAction | RunWorkflowAction;

export type OntologyActionOut = {
  id: string;
  name: string;
  workflow_key: string;
  description: string | null;
  input_schema: JsonSchemaLike | null;
  object_type: string | null;
  requires_capability: string;
  approval_required?: boolean;
  preconditions?: Record<string, unknown> | null;
  enabled: boolean;
  validation_rules?: unknown[] | null;
  webhook_url?: string | null;
  can_run?: boolean | null;
  permission_explanation?: string | null;
};

export type JsonSchemaLike = {
  required?: string[];
  properties?: Record<string, { type?: string; description?: string; enum?: unknown[] }>;
  [key: string]: unknown;
};

export type ActionPreview = {
  action_id: string;
  action_name: string;
  allowed: boolean;
  approval_required: boolean;
  preconditions_ok: boolean;
  missing_preconditions: string[];
  side_effects: Array<Record<string, unknown>>;
  required_capability: string;
};

export type ActionTriggerResult = {
  status: "succeeded" | "queued" | "pending_approval" | "failed" | string;
  action_run_id?: string;
  approval_request_id?: string;
  output?: unknown;
  job_id?: string;
};

export function listActions(objectType?: string): Promise<OntologyActionOut[]> {
  const suffix = objectType ? `?object_type=${encodeURIComponent(objectType)}` : "";
  return apiFetch<OntologyActionOut[]>(`/actions${suffix}`);
}

export function previewAction(actionName: string, params: Record<string, unknown>): Promise<ActionPreview> {
  return apiFetch<ActionPreview>("/actions/preview", {
    method: "POST",
    body: JSON.stringify({ action_name: actionName, params }),
  });
}

export function triggerAction(
  actionName: string,
  params: Record<string, unknown>,
  idempotencyKey: string,
): Promise<ActionTriggerResult> {
  return apiFetch<ActionTriggerResult>("/actions/trigger", {
    method: "POST",
    body: JSON.stringify({ action_name: actionName, params, idempotency_key: idempotencyKey }),
  });
}
