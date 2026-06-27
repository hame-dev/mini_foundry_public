"use client";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import DashboardCanvas from "@/components/dashboards/DashboardCanvas";
import FilterBar from "@/components/dashboards/FilterBar";
import { ResourceComments } from "@/components/platform/ResourceComments";
import { DashboardVariablesProvider } from "@/contexts/DashboardVariables";
import type { ComponentRender, DashboardDetail, RenderOut } from "@/lib/dashboards";

export default function DashboardViewerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [detail, setDetail] = useState<DashboardDetail | null>(null);
  const [renders, setRenders] = useState<Record<string, ComponentRender | undefined>>({});
  const [filters, setFilters] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeTab, setActiveTab] = useState("View");
  const [platformResourceId, setPlatformResourceId] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<DashboardDetail>(`/dashboards/${id}`).then(setDetail).catch((e) => setError(e.message));
    apiFetch<{ id: string; object_id: string | null }[]>("/platform/resources?resource_type=dashboard&limit=500")
      .then((rows) => setPlatformResourceId(rows.find((row) => row.object_id === id)?.id ?? null))
      .catch(() => setPlatformResourceId(null));
  }, [id]);

  const refresh = useCallback(async (f: Record<string, unknown>) => {
    try {
      const out = await apiFetch<RenderOut>(`/dashboards/${id}/render`, {
        method: "POST",
        body: JSON.stringify({ filters: f }),
      });
      const next: Record<string, ComponentRender> = {};
      for (const r of out.components) next[r.id] = r;
      setRenders(next);
      setRenderError(null);
    } catch (e: unknown) {
      setRenderError(e instanceof Error ? e.message : String(e));
    }
  }, [id]);

  useEffect(() => {
    if (detail) refresh(filters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail]);

  async function publish() {
    setBusy(true);
    try {
      const d = await apiFetch<DashboardDetail>(`/dashboards/${id}/publish`, { method: "POST" });
      setDetail(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm("Delete this dashboard?")) return;
    await apiFetch(`/dashboards/${id}`, { method: "DELETE" });
    location.href = "/dashboards";
  }

  async function share() {
    const subjectType = prompt("Share with: everyone, user, or role", "everyone") || "everyone";
    const subjectId = subjectType === "everyone" ? null : prompt("User or role UUID to share with");
    if (subjectType !== "everyone" && !subjectId) return;
    await apiFetch(`/dashboards/${id}/permissions`, {
      method: "POST",
      body: JSON.stringify({
        subject_type: subjectType,
        subject_id: subjectId,
        can_view: true,
        can_edit: false,
        can_share: false,
        can_manage: false,
      }),
    });
  }

  const [activePage, setActivePage] = useState<string | null>(null);

  const pages = (detail as any)?.pages as Array<{ id: string; title: string; component_ids: string[] }> | null | undefined;

  useEffect(() => {
    if (pages && pages.length > 0 && !activePage) {
      setActivePage(pages[0].id);
    }
  }, [pages, activePage]);

  const handleFilterUpdate = useCallback((filterId: string, value: unknown) => {
    const next = { ...filters, [filterId]: value };
    setFilters(next);
    refresh(next);
  }, [filters, refresh]);

  if (error) return <div className="text-red-600">Load failed: {error}</div>;
  if (!detail) return <div>Loading...</div>;

  // Filter components visible on the active page (if multi-page)
  const activePageDef = pages?.find((p) => p.id === activePage);
  const allGridComponents = detail.components.filter(
    (c) => c.component_type !== "filter_date" && c.component_type !== "filter_select",
  );
  const gridComponents = activePageDef
    ? allGridComponents.filter((c) => activePageDef.component_ids.includes(c.id))
    : allGridComponents;

  return (
    <DashboardVariablesProvider>
      <div className="space-y-4">
        <header className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold">{detail.title}</h1>
            {detail.description && <p className="text-sm text-gray-500 mt-1">{detail.description}</p>}
          </div>
          <div className="flex gap-2">
            <span className="badge">{detail.published_at ? `Published v${detail.published_version}` : "Draft only"}</span>
            <button className="btn-ghost" onClick={publish} disabled={busy}>Publish</button>
            <button className="btn-ghost" onClick={share}>Share</button>
            <Link href={`/dashboards/${id}/edit`} className="btn-ghost">Edit</Link>
            <button className="btn-ghost" onClick={remove}>Delete</button>
          </div>
        </header>
        <nav className="foundry-tabs">
          {["View", "Data", "Render errors", "History"].map((tab) => (
            <button key={tab} type="button" className={`foundry-tab ${activeTab === tab ? "foundry-tab-active" : ""}`} onClick={() => setActiveTab(tab)}>{tab}</button>
          ))}
        </nav>
        {renderError ? <div className="badge badge-danger">Render request failed: {renderError}</div> : null}

        {activeTab === "Data" ? (
          <pre className="app-card" style={{ padding: 12, overflow: "auto" }}>{JSON.stringify(renders, null, 2)}</pre>
        ) : activeTab === "Render errors" ? (
          <main className="app-card" style={{ padding: 12 }}>
            {Object.values(renders).filter((r) => r?.error).map((r) => <div key={r!.id} className="badge badge-danger" style={{ display: "block", marginBottom: 8 }}>{r!.error}</div>)}
            {!Object.values(renders).some((r) => r?.error) ? <div className="empty-state"><div className="empty-state-title">No render errors.</div></div> : null}
          </main>
        ) : activeTab === "History" ? (
          <main className="app-card" style={{ padding: 12 }}>
            <div>Published version: {detail.published_version || 0}</div>
            <div>Updated: {new Date(detail.updated_at).toLocaleString()}</div>
          </main>
        ) : (
        <>
        {/* Multi-page tabs */}
        {pages && pages.length > 1 && (
          <div className="flex gap-1" style={{ borderBottom: "1px solid var(--line)" }}>
            {pages.map((p) => (
              <button
                key={p.id}
                onClick={() => setActivePage(p.id)}
                style={activePage === p.id ? { color: "var(--accent)", borderBottom: "2px solid var(--accent)" } : undefined}
                className={`px-4 py-2 text-sm font-medium transition-colors ${
                  activePage === p.id
                    ? ""
                    : "text-gray-500 hover:text-gray-800"
                }`}
              >
                {p.title}
              </button>
            ))}
          </div>
        )}

        {detail.layout.filters?.length > 0 && (
          <FilterBar filters={detail.layout.filters} onChange={(v) => { setFilters(v); refresh(v); }} />
        )}

        <DashboardCanvas
          components={gridComponents}
          renders={renders}
          editable={false}
          onFilterUpdate={handleFilterUpdate}
          filters={filters}
        />
        </>
        )}
        {platformResourceId ? <ResourceComments resourceId={platformResourceId} /> : null}
      </div>
    </DashboardVariablesProvider>
  );
}
