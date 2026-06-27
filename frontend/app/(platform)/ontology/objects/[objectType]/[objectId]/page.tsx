import ObjectPage from "../../../../../objects/[type]/[id]/page";

export default function PlatformOntologyObjectPage({ params }: { params: Promise<{ objectType: string; objectId: string }> }) {
  const mappedParams = params.then(({ objectType, objectId }) => ({ type: objectType, id: objectId }));
  return <ObjectPage params={mappedParams} />;
}
