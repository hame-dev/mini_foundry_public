import { PipelineSubroutePanel } from "@/components/pipelines/PipelineSubroutePanel";

export default function PipelineBranchesPage({ params }: { params: Promise<{ id: string }> }) {
  return <PipelineSubroutePanel params={params} mode="branches" />;
}
