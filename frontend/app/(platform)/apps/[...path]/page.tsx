import { PlatformCatchAllPage } from "@/components/platform/PlatformCatchAll";

export default function AppsCatchAll({ params }: { params: Promise<{ path?: string[] }> }) {
  return <PlatformCatchAllPage section="apps" params={params} />;
}
