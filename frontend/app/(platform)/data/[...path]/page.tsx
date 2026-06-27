import { PlatformCatchAllPage } from "@/components/platform/PlatformCatchAll";

export default function DataCatchAll({ params }: { params: Promise<{ path?: string[] }> }) {
  return <PlatformCatchAllPage section="data" params={params} />;
}
