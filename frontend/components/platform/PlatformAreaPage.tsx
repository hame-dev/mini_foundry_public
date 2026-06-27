"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { ResourceHeader } from "./ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "./States";

type Resource = {
  id: string;
  name: string;
  resource_type: string;
  owner_user_id?: string | null;
  updated_at: string;
};

export function PlatformAreaPage({
  title,
  type,
  resourceType,
  links = [],
}: {
  title: string;
  type: string;
  resourceType?: string;
  links?: { href: string; label: string }[];
}) {
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(Boolean(resourceType));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!resourceType) return;
    apiFetch<Resource[]>(`/platform/resources?resource_type=${encodeURIComponent(resourceType)}&limit=50`)
      .then((rows) => {
        setResources(rows);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load resources"))
      .finally(() => setLoading(false));
  }, [resourceType]);

  return (
    <div className="space-y-4">
      <ResourceHeader title={title} type={type} />
      {links.length > 0 && (
        <div className="app-card p-3 flex flex-wrap gap-2">
          {links.map((link) => (
            <Link key={link.href} className="topbar-pill" href={link.href}>
              {link.label}
            </Link>
          ))}
        </div>
      )}
      {resourceType ? (
        error ? (
          <ErrorState message={error} />
        ) : loading ? (
          <LoadingState label={`Loading ${title.toLowerCase()}...`} />
        ) : resources.length === 0 ? (
          <EmptyState title={`No ${title.toLowerCase()} yet`} detail="Create or ingest a governed resource to populate this view." />
        ) : (
          <div className="app-card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[var(--muted)] border-b border-[var(--line)]">
                  <th className="p-3">Name</th>
                  <th className="p-3">Type</th>
                  <th className="p-3">Updated</th>
                </tr>
              </thead>
              <tbody>
                {resources.map((resource) => (
                  <tr key={resource.id} className="border-b border-[var(--line-soft)]">
                    <td className="p-3">{resource.name}</td>
                    <td className="p-3">{resource.resource_type}</td>
                    <td className="p-3">{new Date(resource.updated_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : (
        <EmptyState title={`${title} workspace`} detail="This route is wired into the platform shell and ready for resource-backed workflow screens." />
      )}
    </div>
  );
}
