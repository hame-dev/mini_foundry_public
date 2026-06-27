import { redirect } from "next/navigation";

export default async function SpaceDetailPage({ params }: { params: Promise<{ spaceId: string }> }) {
  const { spaceId } = await params;
  redirect(`/workspace/projects/${spaceId}`);
}
