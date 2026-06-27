import { apiFetch } from "./api";

export type Project = {
  id: string;
  name: string;
  description: string | null;
  owner_id: string | null;
  created_at: string;
};

export type ProjectDetail = Project & {
  resource_counts: Record<string, number>;
  resource_total: number;
};

export type PlatformResource = {
  id: string;
  resource_type: string;
  object_id: string | null;
  name: string;
  project_id: string | null;
  updated_at?: string;
};

export type ProjectAccess = {
  id: string;
  subject_type: string;
  subject_id: string | null;
  capabilities: string[];
  inherit: boolean;
};

export type ProjectActivityEvent = {
  id: string;
  event_type: string;
  resource_type: string | null;
  resource_id: string | null;
  user_id: string | null;
  created_at: string;
};

export type ProjectBranch = {
  id: string;
  name: string;
  status: string;
  project_id: string | null;
  parent_branch_id: string | null;
  created_by: string | null;
  created_at: string;
  merged_at: string | null;
};

export type BranchChange = {
  resource_id: string;
  resource_type: string | null;
  name: string | null;
  branch_version_id: string;
  branch_version_number: number;
  main_changed_after_branch: boolean;
  main_version_id?: string;
  main_version_number?: number;
};

export type BranchCompare = {
  branch: ProjectBranch;
  changes: BranchChange[];
  conflicts: BranchChange[];
  mergeable: boolean;
};

export const PROJECT_CAPABILITIES = [
  "view_metadata", "view_data", "use_in_sql", "use_in_python", "use_with_ai",
  "run", "edit", "manage", "export", "grant", "publish", "writeback",
];

export function listProjects(): Promise<Project[]> {
  return apiFetch<Project[]>("/platform/projects");
}

export function createProject(payload: { name: string; description?: string | null }): Promise<Project> {
  return apiFetch<Project>("/platform/projects", { method: "POST", body: JSON.stringify(payload) });
}

export function getProject(projectId: string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>(`/platform/projects/${projectId}`);
}

export function listProjectResources(projectId: string): Promise<PlatformResource[]> {
  return apiFetch<PlatformResource[]>(`/platform/resources?project_id=${encodeURIComponent(projectId)}&limit=200`);
}

export function listProjectAccess(projectId: string): Promise<ProjectAccess[]> {
  return apiFetch<ProjectAccess[]>(`/platform/projects/${projectId}/access`);
}

export function grantProjectAccess(projectId: string, payload: { subject_type: string; subject_id?: string | null; capabilities: string[] }): Promise<ProjectAccess> {
  return apiFetch<ProjectAccess>(`/platform/projects/${projectId}/access`, { method: "POST", body: JSON.stringify(payload) });
}

export function revokeProjectAccess(projectId: string, aclId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/platform/projects/${projectId}/access/${aclId}`, { method: "DELETE" });
}

export function listProjectActivity(projectId: string): Promise<{ project_id: string; events: ProjectActivityEvent[] }> {
  return apiFetch<{ project_id: string; events: ProjectActivityEvent[] }>(`/platform/projects/${projectId}/activity`);
}

export function listProjectBranches(projectId: string): Promise<ProjectBranch[]> {
  return apiFetch<ProjectBranch[]>(`/platform/branches?project_id=${encodeURIComponent(projectId)}`);
}

export function listBranches(params: { projectId?: string; status?: string } = {}): Promise<ProjectBranch[]> {
  const qs = new URLSearchParams();
  if (params.projectId) qs.set("project_id", params.projectId);
  if (params.status) qs.set("status_filter", params.status);
  return apiFetch<ProjectBranch[]>(`/platform/branches${qs.size ? `?${qs.toString()}` : ""}`);
}

export function createProjectBranch(payload: { name: string; project_id?: string | null; parent_branch_id?: string | null }): Promise<ProjectBranch> {
  return apiFetch<ProjectBranch>("/platform/branches", { method: "POST", body: JSON.stringify(payload) });
}

export function compareBranch(branchId: string): Promise<BranchCompare> {
  return apiFetch<BranchCompare>(`/platform/branches/${branchId}/compare`);
}

export function requestBranchReview(branchId: string, note?: string): Promise<{ ok: boolean; status: string }> {
  return apiFetch<{ ok: boolean; status: string }>(`/platform/branches/${branchId}/review`, {
    method: "POST",
    body: JSON.stringify({ note: note || null }),
  });
}

export function mergeProjectBranch(branchId: string): Promise<{ ok: boolean; status: string; merged_versions: string[] }> {
  return apiFetch<{ ok: boolean; status: string; merged_versions: string[] }>(`/platform/branches/${branchId}/merge`, { method: "POST" });
}

export function abandonProjectBranch(branchId: string): Promise<{ ok: boolean; status: string }> {
  return apiFetch<{ ok: boolean; status: string }>(`/platform/branches/${branchId}/abandon`, { method: "POST" });
}
