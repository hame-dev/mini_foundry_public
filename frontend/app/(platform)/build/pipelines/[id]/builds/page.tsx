import { PipelineSubroutePanel } from "@/components/pipelines/PipelineSubroutePanel";

export default function PipelineBuildsPage({ params }: { params: Promise<{ id: string }> }) {
  return <PipelineSubroutePanel params={params} mode="builds" />;
}
