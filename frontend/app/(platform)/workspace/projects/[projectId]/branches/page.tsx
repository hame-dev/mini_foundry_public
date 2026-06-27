"use client";

import { use } from "react";
import { ProjectDetail } from "@/components/platform/ProjectDetail";

export default function ProjectBranchesPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = use(params);
  return <ProjectDetail projectId={projectId} initialTab="branches" />;
}
