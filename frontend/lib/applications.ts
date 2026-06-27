import { apiFetch } from "./api";

export type AppPage = {
  id?: string;
  title: string;
  page_type: string;
  object_type: string | null;
  config: Record<string, unknown>;
  role_visibility?: string[];
  position: number;
};

export type Application = {
  id: string;
  name: string;
  description: string | null;
  config: Record<string, unknown>;
  status: string;
  pages: AppPage[];
  updated_at: string;
  published_at?: string | null;
  branch_name?: string;
};

export function listApplications(): Promise<Application[]> {
  return apiFetch<Application[]>("/applications");
}

export function getApplication(appId: string): Promise<Application> {
  return apiFetch<Application>(`/applications/${appId}`);
}

export function createApplication(payload: {
  name: string;
  description?: string | null;
  config?: Record<string, unknown>;
  pages?: AppPage[];
  branch_name?: string;
}): Promise<Application> {
  return apiFetch<Application>("/applications", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateApplication(appId: string, payload: {
  name: string;
  description?: string | null;
  config?: Record<string, unknown>;
  pages?: AppPage[];
  branch_name?: string;
}): Promise<Application> {
  return apiFetch<Application>(`/applications/${appId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function publishApplication(appId: string, branchName = "main"): Promise<Application> {
  return apiFetch<Application>(`/applications/${appId}/publish?branch_name=${encodeURIComponent(branchName)}`, {
    method: "POST",
  });
}

export type AppVersion = {
  id: string;
  version_number: number;
  created_at: string;
  published_at: string | null;
};

export type PublishedApp = {
  id: string;
  name: string;
  pages: AppPage[];
  config: Record<string, unknown>;
  published_at: string | null;
  published_version: number | null;
  mode: "published" | "preview";
  notices: Array<{ type: string; reason: string }>;
};

export type AppLineageEdge = {
  source_resource_id: string | null;
  source_name: string | null;
  source_type: string | null;
  edge_type: string;
  metadata?: Record<string, unknown>;
};

export function listAppVersions(appId: string): Promise<AppVersion[]> {
  return apiFetch<AppVersion[]>(`/applications/${appId}/versions`);
}

export function getAppVersion(appId: string, versionId: string): Promise<{
  id: string;
  version_number: number;
  manifest: Record<string, unknown>;
}> {
  return apiFetch(`/applications/${appId}/versions/${versionId}`);
}

export function getPublishedApp(appId: string): Promise<PublishedApp> {
  return apiFetch<PublishedApp>(`/applications/${appId}/published`);
}

export function previewApplication(appId: string): Promise<PublishedApp> {
  return apiFetch<PublishedApp>(`/applications/${appId}/preview`);
}

export function getAppLineage(appId: string): Promise<AppLineageEdge[]> {
  return apiFetch<AppLineageEdge[]>(`/applications/${appId}/lineage`);
}
