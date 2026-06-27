import { PipelineSubroutePanel } from "@/components/pipelines/PipelineSubroutePanel";

export default function PipelineExpectationsPage({ params }: { params: Promise<{ id: string }> }) {
  return <PipelineSubroutePanel params={params} mode="expectations" />;
}
