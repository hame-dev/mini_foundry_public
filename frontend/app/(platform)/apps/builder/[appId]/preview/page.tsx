"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/api";
import { previewApplication, type PublishedApp } from "@/lib/applications";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { ErrorState, LoadingState } from "@/components/platform/States";
import { AppRuntimeView } from "@/components/applications/AppRuntimeView";

export default function AppPreviewPage({ params }: { params: Promise<{ appId: string }> }) {
  const { appId } = use(params);
  const [app, setApp] = useState<PublishedApp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setApp(await previewApplication(appId));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load preview.");
    } finally {
      setLoading(false);
    }
  }, [appId]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="space-y-5">
      <ResourceHeader
        title={app?.name ?? "App preview"}
        type="App - Draft preview"
        status="Draft"
        actions={<Link className="btn-ghost text-xs" href={`/apps/builder/${appId}`}>Back to builder</Link>}
      />
      {loading ? <LoadingState label="Loading app preview..." /> : null}
      {error ? <ErrorState message={error} /> : null}
      {!loading && !error && app ? <AppRuntimeView app={app} /> : null}
    </div>
  );
}
