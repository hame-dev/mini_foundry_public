import { PlatformCatchAllPage } from "@/components/platform/PlatformCatchAll";

export default function AiCatchAll({ params }: { params: Promise<{ path?: string[] }> }) {
  return <PlatformCatchAllPage section="ai" params={params} />;
}
