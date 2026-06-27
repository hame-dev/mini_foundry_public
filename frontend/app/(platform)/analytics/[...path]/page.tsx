import { PlatformCatchAllPage } from "@/components/platform/PlatformCatchAll";

export default function AnalyticsCatchAll({ params }: { params: Promise<{ path?: string[] }> }) {
  return <PlatformCatchAllPage section="analytics" params={params} />;
}
