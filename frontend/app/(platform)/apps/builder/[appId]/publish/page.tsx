"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/api";
import { getApplication, publishApplication, previewApplication, type Application, type PublishedApp } from "@/lib/applications";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { ErrorState, LoadingState } from "@/components/platform/States";
import { AppRuntimeView } from "@/components/applications/AppRuntimeView";
import { useActiveBranch } from "@/lib/branchContext";

export default function AppPublishPage({ params }: { params: Promise<{ appId: string }> }) {
  const { appId } = use(params);
  const [app, setApp] = useState<Application | null>(null);
  const [preview, setPreview] = useState<PublishedApp | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { branchName, setBranchName } = useActiveBranch();
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextApp, nextPreview] = await Promise.all([getApplication(appId), previewApplication(appId)]);
      setApp(nextApp);
      setPreview(nextPreview);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load publish review.");
    } finally {
      setLoading(false);
    }
  }, [appId]);

  useEffect(() => { void load(); }, [load]);

  async function publish() {
    setSaving(true);
    try {
      const published = await publishApplication(appId, branchName || "main");
      setApp(published);
      setMessage(`Published ${published.published_at ? new Date(published.published_at).toLocaleString() : "successfully"}.`);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to publish app.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader
        title={app?.name ?? "Publish app"}
        type="App - Publish"
        status={app?.status ?? "Draft"}
        actions={(
          <div className="flex flex-wrap gap-2">
            <input className="input-dark h-8 w-28 text-xs" value={branchName} onChange={(event) => setBranchName(event.target.value)} aria-label="Branch name" />
            <Link className="btn-ghost text-xs" href={`/apps/builder/${appId}`}>Back to builder</Link>
            <button className="btn-primary text-xs" disabled={saving || loading} onClick={() => void publish()}>{saving ? "Publishing..." : "Publish"}</button>
          </div>
        )}
      />
      {loading ? <LoadingState label="Loading publish review..." /> : null}
      {message ? <div className="app-card p-3 text-sm text-[var(--success)]">{message}</div> : null}
      {error ? <ErrorState message={error} /> : null}
      {preview ? (
        <>
          <section className="app-card p-3">
            <h2 className="section-header-title mb-2">Publish review</h2>
            <div className="grid gap-2 text-sm md:grid-cols-3">
              <div><span className="text-[var(--muted)]">Visible pages</span><div className="font-semibold">{preview.pages.length}</div></div>
              <div><span className="text-[var(--muted)]">Runtime notices</span><div className="font-semibold">{preview.notices.length}</div></div>
              <div><span className="text-[var(--muted)]">Current version</span><div className="font-semibold">{app?.published_at ? "Published" : "Unpublished"}</div></div>
            </div>
          </section>
          <AppRuntimeView app={preview} />
        </>
      ) : null}
    </div>
  );
}
