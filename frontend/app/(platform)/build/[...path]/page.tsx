import { PlatformCatchAllPage } from "@/components/platform/PlatformCatchAll";

export default function BuildCatchAll({ params }: { params: Promise<{ path?: string[] }> }) {
  return <PlatformCatchAllPage section="build" params={params} />;
}
