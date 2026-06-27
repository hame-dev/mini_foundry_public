import { PlatformCatchAllPage } from "@/components/platform/PlatformCatchAll";

export default function DevelopCatchAll({ params }: { params: Promise<{ path?: string[] }> }) {
  return <PlatformCatchAllPage section="develop" params={params} />;
}
