import { apiFetch } from "@/lib/api";

export type ResourceRef = {
  id: string;
  resource_type: string;
  name: string;
  project_id?: string | null;
  parent_resource_id?: string | null;
};

export const resourcesApi = {
  search(params: { q?: string; resource_type?: string } = {}) {
    const query = new URLSearchParams();
    if (params.q) query.set("q", params.q);
    if (params.resource_type) query.set("resource_type", params.resource_type);
    return apiFetch<ResourceRef[]>(`/platform/resources?${query.toString()}`);
  },
  explain(resourceId: string, capability: string) {
    return apiFetch(`/platform/resources/${resourceId}/permissions/explain?capability=${encodeURIComponent(capability)}`);
  },
};
