"use client";

import { use } from "react";
import { PlatformAreaPage } from "./PlatformAreaPage";

const RESOURCE_TYPES: Record<string, string> = {
  sources: "data_source",
  datasets: "dataset",
  catalog: "dataset",
  pipelines: "pipeline",
  dashboards: "dashboard",
  builder: "application",
  published: "application",
  notebooks: "notebook",
  code: "code_repository",
  models: "model",
  manager: "ontology_object_type",
  "object-types": "ontology_object_type",
  actions: "ontology_action",
  jobs: "job",
};

export function PlatformCatchAllPage({
  section,
  params,
}: {
  section: string;
  params: Promise<{ path?: string[] }>;
}) {
  const { path = [] } = use(params);
  const key = path[0] || section;
  const title = [section, ...path]
    .filter(Boolean)
    .map((part) => part.replace(/-/g, " "))
    .join(" / ");
  return (
    <PlatformAreaPage
      title={title ? title.replace(/\b\w/g, (c) => c.toUpperCase()) : section}
      type={section}
      resourceType={RESOURCE_TYPES[key]}
    />
  );
}
