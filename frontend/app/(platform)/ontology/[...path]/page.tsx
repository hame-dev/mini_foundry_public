import { PlatformCatchAllPage } from "@/components/platform/PlatformCatchAll";

export default function OntologyCatchAll({ params }: { params: Promise<{ path?: string[] }> }) {
  return <PlatformCatchAllPage section="ontology" params={params} />;
}
