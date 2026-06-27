import { PipelineSubroutePanel } from "@/components/pipelines/PipelineSubroutePanel";

export default function PipelineSchedulesPage({ params }: { params: Promise<{ id: string }> }) {
  return <PipelineSubroutePanel params={params} mode="schedules" />;
}
