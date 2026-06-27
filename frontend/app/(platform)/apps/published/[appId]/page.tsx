"use client";

import { use, useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { getPublishedApp, type PublishedApp } from "@/lib/applications";
import { ApiError } from "@/lib/api";
import { AppRuntimeView } from "@/components/applications/AppRuntimeView";

export default function PublishedAppPage({ params }: { params: Promise<{ appId: string }> }) {
  const { appId } = use(params);
  const [app, setApp] = useState<PublishedApp | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notPublished, setNotPublished] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotPublished(false);
    try {
      setApp(await getPublishedApp(appId));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotPublished(true);
      } else {
        setError(err instanceof ApiError ? err.message : "Unable to load published app.");
      }
    } finally {
      setLoading(false);
    }
  }, [appId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-5">
      <ResourceHeader
        title={app?.name ?? "Published app"}
        type="App · Published"
        status={app?.published_version ? `v${app.published_version}` : "Published"}
        subtitle={app?.published_at ? `Published ${new Date(app.published_at).toLocaleString()}` : undefined}
      />

      {loading ? <LoadingState label="Loading published app..." /> : null}
      {error ? <ErrorState message={error} /> : null}
      {notPublished ? <EmptyState title="Not published yet" detail="Publish this app from the builder to make a stable viewer available." /> : null}

      {!loading && !error && app ? <AppRuntimeView app={app} /> : null}
    </div>
  );
}
