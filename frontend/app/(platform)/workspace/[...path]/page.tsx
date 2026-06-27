"use client";

import { use } from "react";
import { PlatformAreaPage } from "@/components/platform/PlatformAreaPage";

const RESOURCE_TYPES: Record<string, string | undefined> = {
  spaces: "project",
  projects: "project",
  folders: "folder",
  resources: undefined,
  "access-requests": undefined,
  branches: undefined,
  activity: undefined,
};

const LINKS = [
  { href: "/workspace/projects", label: "Projects" },
  { href: "/workspace/spaces", label: "Spaces" },
  { href: "/workspace/resources", label: "Resources" },
  { href: "/workspace/access-requests", label: "Access requests" },
  { href: "/workspace/branches", label: "Branches" },
  { href: "/workspace/activity", label: "Activity" },
];

export default function WorkspaceSubroutePage({ params }: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = use(params);
  const key = path[0] || "resources";
  const title = ["Workspace", ...path]
    .map((part) => part.replace(/-/g, " "))
    .join(" / ")
    .replace(/\b\w/g, (char) => char.toUpperCase());

  return (
    <PlatformAreaPage
      title={title}
      type="Workspace"
      resourceType={RESOURCE_TYPES[key]}
      links={LINKS}
    />
  );
}
