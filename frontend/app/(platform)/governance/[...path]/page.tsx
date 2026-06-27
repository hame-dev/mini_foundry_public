import { PlatformCatchAllPage } from "@/components/platform/PlatformCatchAll";

export default function GovernanceCatchAll({ params }: { params: Promise<{ path?: string[] }> }) {
  return <PlatformCatchAllPage section="governance" params={params} />;
}
