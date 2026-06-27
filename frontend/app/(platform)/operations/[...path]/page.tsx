import { PlatformCatchAllPage } from "@/components/platform/PlatformCatchAll";

export default function OperationsCatchAll({ params }: { params: Promise<{ path?: string[] }> }) {
  return <PlatformCatchAllPage section="operations" params={params} />;
}
