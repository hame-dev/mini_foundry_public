import { apiFetch } from "./api";

export type AccessRequest = {
  id: string;
  resource_id: string;
  requester_id: string | null;
  capabilities: string[];
  reason: string | null;
  status: string;
  created_at: string;
};

export type ApprovalRequest = {
  id: string;
  resource_id: string | null;
  requester_id: string | null;
  approval_type: string;
  status: string;
  details: Record<string, unknown>;
  decided_by: string | null;
  decision_note: string | null;
  created_at: string;
  decided_at: string | null;
};

export type ExportRequest = {
  id: string;
  resource_id: string | null;
  requester_id: string | null;
  purpose: string;
  destination: string | null;
  status: string;
  approval_request_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
};

export type GovernanceGroup = {
  id: string;
  name: string;
  description: string | null;
  member_count: number;
  created_at: string;
};

export type GovernanceGroupMember = {
  id: string;
  email: string;
  name: string | null;
};

export type Marking = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
};

export type MarkingEligibility = {
  id: string;
  principal_type: "user" | "role" | "group" | "all_users";
  principal_id: string | null;
  marking_name: string;
  created_at: string;
};

export function listAccessRequests(status = "pending"): Promise<{ requests: AccessRequest[] }> {
  return apiFetch<{ requests: AccessRequest[] }>(`/platform/access-requests?status_filter=${encodeURIComponent(status)}`);
}

export function decideAccessRequest(requestId: string, approve: boolean, note?: string): Promise<{ ok: boolean; status: string }> {
  return apiFetch<{ ok: boolean; status: string }>(`/platform/access-requests/${requestId}/decision`, {
    method: "POST",
    body: JSON.stringify({ approve, note: note || null }),
  });
}

export function listApprovals(status = "pending"): Promise<ApprovalRequest[]> {
  return apiFetch<ApprovalRequest[]>(`/platform/approvals?status_filter=${encodeURIComponent(status)}`);
}

export function decideApproval(approvalId: string, approve: boolean, note?: string): Promise<{ ok: boolean; status: string; action?: unknown }> {
  return apiFetch<{ ok: boolean; status: string; action?: unknown }>(`/platform/approvals/${approvalId}/decision`, {
    method: "POST",
    body: JSON.stringify({ approve, note: note || null }),
  });
}

export function listExports(status?: string): Promise<ExportRequest[]> {
  const suffix = status ? `?status_filter=${encodeURIComponent(status)}` : "";
  return apiFetch<ExportRequest[]>(`/platform/exports${suffix}`);
}

export function createExportRequest(payload: {
  resource_id: string;
  purpose: string;
  destination?: string | null;
  details?: Record<string, unknown>;
}): Promise<ExportRequest> {
  return apiFetch<ExportRequest>("/platform/exports", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listGroups(): Promise<GovernanceGroup[]> {
  return apiFetch<GovernanceGroup[]>("/governance/groups");
}

export function createGroup(payload: { name: string; description?: string | null }): Promise<GovernanceGroup> {
  return apiFetch<GovernanceGroup>("/governance/groups", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listGroupMembers(groupId: string): Promise<{ group_id: string; members: GovernanceGroupMember[] }> {
  return apiFetch<{ group_id: string; members: GovernanceGroupMember[] }>(`/governance/groups/${groupId}/members`);
}

export function addGroupMember(groupId: string, userId: string): Promise<{ ok: boolean; permission_version: number }> {
  return apiFetch<{ ok: boolean; permission_version: number }>(`/governance/groups/${groupId}/members`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
}

export function removeGroupMember(groupId: string, userId: string): Promise<{ ok: boolean; permission_version: number }> {
  return apiFetch<{ ok: boolean; permission_version: number }>(`/governance/groups/${groupId}/members/${userId}`, {
    method: "DELETE",
  });
}

export function listMarkings(): Promise<Marking[]> {
  return apiFetch<Marking[]>("/governance/markings");
}

export function createMarking(payload: { name: string; description?: string | null }): Promise<Marking> {
  return apiFetch<Marking>("/governance/markings", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listMarkingEligibility(): Promise<MarkingEligibility[]> {
  return apiFetch<MarkingEligibility[]>("/governance/markings/eligibility");
}

export function grantMarkingEligibility(payload: {
  principal_type: MarkingEligibility["principal_type"];
  principal_id?: string | null;
  marking_name: string;
}): Promise<MarkingEligibility> {
  return apiFetch<MarkingEligibility>("/governance/markings/eligibility", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function revokeMarkingEligibility(eligibilityId: string): Promise<{ ok: boolean; permission_version: number }> {
  return apiFetch<{ ok: boolean; permission_version: number }>(`/governance/markings/eligibility/${eligibilityId}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------- roles

export type GovernanceRole = { id: string; name: string; member_count: number };

export function listRoles(): Promise<GovernanceRole[]> {
  return apiFetch<GovernanceRole[]>("/governance/roles");
}

export function createRole(name: string): Promise<GovernanceRole> {
  return apiFetch<GovernanceRole>("/governance/roles", { method: "POST", body: JSON.stringify({ name }) });
}

export function deleteRole(roleId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/governance/roles/${roleId}`, { method: "DELETE" });
}

// ------------------------------------------------------------ capabilities

export type Capability = { name: string; description: string };
export type CapabilityGrant = {
  resource_id: string;
  resource_type: string;
  resource_name: string;
  subject_type: string;
  subject_id: string | null;
  capabilities: string[];
};

export function listCapabilities(): Promise<Capability[]> {
  return apiFetch<Capability[]>("/governance/capabilities");
}

export function listCapabilityGrants(): Promise<CapabilityGrant[]> {
  return apiFetch<CapabilityGrant[]>("/governance/capabilities/grants");
}

// ------------------------------------------------------------- row policies

export type RowPolicy = {
  id: string;
  dataset_id: string;
  subject_type: string;
  subject_id: string | null;
  sql_condition: string;
  condition_json: Record<string, unknown> | null;
};

export function listRowPolicies(datasetId?: string): Promise<RowPolicy[]> {
  const q = datasetId ? `?dataset_id=${encodeURIComponent(datasetId)}` : "";
  return apiFetch<RowPolicy[]>(`/governance/row-policies${q}`);
}

export function createRowPolicy(payload: {
  dataset_id: string;
  subject_type: string;
  subject_id: string;
  condition_json: Record<string, unknown>;
}): Promise<RowPolicy> {
  return apiFetch<RowPolicy>("/governance/row-policies", { method: "POST", body: JSON.stringify(payload) });
}

export function deleteRowPolicy(id: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/governance/row-policies/${id}`, { method: "DELETE" });
}

// ------------------------------------------------------------- column masks

export type ColumnMask = {
  id: string;
  dataset_id: string;
  column_name: string;
  subject_type: string;
  subject_id: string | null;
  mask_type: string | null;
};

export const MASK_TYPES = ["hidden", "null", "hash", "partial", "none"] as const;

export function listColumnMasks(datasetId?: string): Promise<ColumnMask[]> {
  const q = datasetId ? `?dataset_id=${encodeURIComponent(datasetId)}` : "";
  return apiFetch<ColumnMask[]>(`/governance/column-masks${q}`);
}

export function createColumnMask(payload: {
  dataset_id: string;
  column_name: string;
  subject_type: string;
  subject_id: string;
  mask_type: string;
}): Promise<ColumnMask> {
  return apiFetch<ColumnMask>("/governance/column-masks", { method: "POST", body: JSON.stringify(payload) });
}

export function deleteColumnMask(id: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/governance/column-masks/${id}`, { method: "DELETE" });
}

// ----------------------------------------------------------------- secrets

export type Secret = { id: string; name: string | null; description: string | null; created_at: string };

export function listSecrets(): Promise<Secret[]> {
  return apiFetch<Secret[]>("/governance/secrets");
}

export function createSecret(payload: { name: string; description?: string | null; value: string }): Promise<Secret> {
  return apiFetch<Secret>("/governance/secrets", { method: "POST", body: JSON.stringify(payload) });
}

export function deleteSecret(id: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/governance/secrets/${id}`, { method: "DELETE" });
}

// ----------------------------------------------------------- policies overview

export type PoliciesSummary = { row_policy_count: number; column_mask_count: number; acl_grant_count: number };

export function policiesSummary(): Promise<PoliciesSummary> {
  return apiFetch<PoliciesSummary>("/governance/policies/summary");
}

// Datasets are needed by the row-policy and column-mask pickers.
export type GovDataset = { id: string; name: string };

export function listGovDatasets(): Promise<GovDataset[]> {
  return apiFetch<GovDataset[]>("/data/datasets");
}
