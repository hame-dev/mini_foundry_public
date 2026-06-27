"use client";
import { use, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import DashboardCanvas from "@/components/dashboards/DashboardCanvas";
import ComponentPalette from "@/components/dashboards/ComponentPalette";
import PropertiesPanel from "@/components/dashboards/PropertiesPanel";
import DataBindingPanel from "@/components/dashboards/DataBindingPanel";
import { ResourceHeader, ResourceToolbar } from "@/components/foundry/FoundryPrimitives";
import { useActiveBranch } from "@/lib/branchContext";
import type { WidgetDefinition } from "@/lib/types";
import {
  COMPONENT_DEFAULTS,
  type ComponentRender,
  type ComponentType,
  type DashboardComponent,
  type DashboardDetail,
  type DashboardLayout,
  type RenderOut,
} from "@/lib/dashboards";

function uuid(): string {
  return crypto.randomUUID();
}

type PageDef = { id: string; title: string; component_ids: string[] };

export default function DashboardBuilderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [detail, setDetail] = useState<DashboardDetail | null>(null);
  const [components, setComponents] = useState<DashboardComponent[]>([]);
  const [filters, setFilters] = useState<DashboardLayout["filters"]>([]);
  const [renders, setRenders] = useState<Record<string, ComponentRender | undefined>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pages, setPages] = useState<PageDef[]>([]);
  const [activePageId, setActivePageId] = useState<string | null>(null);
  const [widgetPickerOpen, setWidgetPickerOpen] = useState(false);
  const [widgets, setWidgets] = useState<WidgetDefinition[]>([]);
  const [widgetCategory, setWidgetCategory] = useState("All");
  const { branchName, setBranchName } = useActiveBranch();

  useEffect(() => {
    apiFetch<DashboardDetail>(`/dashboards/${id}`).then((d) => {
      setDetail(d);
      setComponents(d.components);
      setFilters(d.layout.filters || []);
      const loadedPages = (d as any).pages as PageDef[] | null;
      if (loadedPages && loadedPages.length > 0) {
        setPages(loadedPages);
        setActivePageId(loadedPages[0].id);
      }
    }).catch((e) => setError(e.message));
    apiFetch<{ widgets: WidgetDefinition[] }>("/dashboards/widgets").then((r) => setWidgets(r.widgets)).catch(() => undefined);
  }, [id]);

  const renderOne = useCallback(async (component: DashboardComponent) => {
    try {
      // Save first if it's not yet persisted? We use a stable id so we can
      // call the dedicated single-component render endpoint. But the
      // backend only knows about components that have been saved. For
      // unsaved changes we POST the whole dashboard render after save —
      // simpler for the MVP. Here we just render whatever the backend has
      // for now.
      const r = await apiFetch<ComponentRender>(
        `/dashboards/${id}/components/${component.id}/render`,
        { method: "POST", body: JSON.stringify({ filters: {} }) },
      );
      setRenders((prev) => ({ ...prev, [component.id]: r }));
    } catch {
      // component not yet saved; ignore
    }
  }, [id]);

  async function renderAll() {
    try {
      const out = await apiFetch<RenderOut>(`/dashboards/${id}/render`, {
        method: "POST",
        body: JSON.stringify({ filters: {} }),
      });
      const next: Record<string, ComponentRender> = {};
      for (const r of out.components) next[r.id] = r;
      setRenders(next);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (detail) renderAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail]);

  function addComponent(type: ComponentType) {
    const defaults = COMPONENT_DEFAULTS[type];
    const next: DashboardComponent = {
      id: uuid(),
      component_type: type,
      title: null,
      position: { ...defaults.position, y: components.length * 2 },
      config: { ...defaults.config },
      data_binding: defaults.binding ? { ...defaults.binding } : null,
      refresh: { mode: "cached", ttl_seconds: 300 },
    };
    setComponents([...components, next]);
    setSelectedId(next.id);
  }

  function updateComponent(updated: DashboardComponent) {
    setComponents(components.map((c) => (c.id === updated.id ? updated : c)));
  }

  function deleteSelected() {
    if (!selectedId) return;
    setComponents(components.filter((c) => c.id !== selectedId));
    setSelectedId(null);
  }

  function handleLayoutChange(positions: Record<string, { x: number; y: number; w: number; h: number }>) {
    setComponents(components.map((c) => positions[c.id] ? { ...c, position: positions[c.id] } : c));
  }

  function addPage() {
    const title = prompt("Page name") || `Page ${pages.length + 1}`;
    const newPage: PageDef = { id: uuid(), title, component_ids: [] };
    setPages([...pages, newPage]);
    setActivePageId(newPage.id);
  }

  function removePage(pageId: string) {
    setPages(pages.filter((p) => p.id !== pageId));
    if (activePageId === pageId) setActivePageId(pages[0]?.id ?? null);
  }

  function assignComponentToPage(componentId: string, pageId: string) {
    setPages(pages.map((p) => ({
      ...p,
      component_ids: p.id === pageId
        ? [...new Set([...p.component_ids, componentId])]
        : p.component_ids.filter((cid) => cid !== componentId),
    })));
  }

  async function save() {
    setBusy(true); setError(null);
    try {
      const layout: DashboardLayout = { version: 1, components, filters };
      await apiFetch(`/dashboards/${id}`, {
        method: "PUT",
        body: JSON.stringify({ layout, pages: pages.length > 0 ? pages : null, branch_name: branchName || "main" }),
      });
      await renderAll();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    await save();
    setBusy(true);
    try {
      const d = await apiFetch<DashboardDetail>(`/dashboards/${id}/publish?branch_name=${encodeURIComponent(branchName || "main")}`, { method: "POST" });
      setDetail(d);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function removeDashboard() {
    if (!confirm("Delete this dashboard?")) return;
    await apiFetch(`/dashboards/${id}`, { method: "DELETE" });
    router.push("/dashboards");
  }

  async function shareDashboard() {
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

  if (error && !detail) return <div className="text-red-600">{error}</div>;
  if (!detail) return <div>Loading...</div>;

  const selected = components.find((c) => c.id === selectedId) || null;

  return (
    <div style={{ display: "grid", gap: 10 }}>
      <ResourceHeader
        eyebrow={detail.dashboard_kind === "workshop" ? "Workshop" : detail.dashboard_kind === "quiver" ? "Quiver" : "Contour"}
        title={detail.title}
        subtitle={detail.description ?? "Module builder with widget picker, canvas layout, preview, and publish controls."}
        tabs={[{ label: "Edit", id: "Edit" }, { label: "Proposals", id: "Proposals" }, { label: "History", id: "History" }]}
        activeTab="Edit"
        actions={
          <>
            <input className="input-dark h-8 w-28 text-xs" value={branchName} onChange={(event) => setBranchName(event.target.value)} aria-label="Branch name" />
            <button onClick={save} disabled={busy} className="btn-ghost">{busy ? "Saving..." : "Save draft"}</button>
            <button onClick={publish} disabled={busy} className="btn-primary">Publish</button>
          </>
        }
      />
      <ResourceToolbar>
        <button className="btn-ghost" onClick={() => setWidgetPickerOpen(true)}>Add widget</button>
        <button className="btn-ghost" onClick={() => router.push(`/dashboards/${id}`)}>Preview</button>
        <button className="btn-ghost" onClick={shareDashboard}>Share</button>
        <button className="btn-ghost" onClick={removeDashboard} style={{ color: "var(--danger)" }}>Delete</button>
        {error ? <span className="badge badge-danger">{error}</span> : null}
      </ResourceToolbar>
      {widgetPickerOpen ? (
        <div style={{ position: "fixed", inset: "8vh 10vw", zIndex: 100, background: "var(--panel)", border: "1px solid var(--line)", boxShadow: "var(--shadow-2)", display: "grid", gridTemplateRows: "auto auto 1fr" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 12, borderBottom: "1px solid var(--line)" }}>
            <input placeholder="Search widgets..." style={{ flex: 1, padding: "8px 10px" }} />
            <button className="btn-ghost" onClick={() => setWidgetPickerOpen(false)}>Close</button>
          </div>
          <div className="foundry-tabs" style={{ padding: "0 12px", margin: 0 }}>
            {["All", "Properties and links", "Visualize", "Filter", "Writeback", "Foundry apps", "Unused widgets"].map((cat) => (
              <button key={cat} className={`foundry-tab ${widgetCategory === cat ? "foundry-tab-active" : ""}`} onClick={() => setWidgetCategory(cat)}>{cat}</button>
            ))}
          </div>
          <div className="foundry-grid" style={{ padding: 16, overflow: "auto" }}>
            {widgets.filter((w) => widgetCategory === "All" || w.category === widgetCategory).map((w) => (
              <button key={w.id} className="app-card" style={{ padding: 16, textAlign: "left", minHeight: 140 }} onClick={() => { addComponent((w.id === "chart_xy" ? "bar_chart" : w.id === "data_table" ? "table" : w.id) as ComponentType); setWidgetPickerOpen(false); }}>
                <div className="badge badge-accent">{w.category}</div>
                <h3 style={{ marginTop: 10 }}>{w.label}</h3>
                <p style={{ color: "var(--muted)" }}>{w.description}</p>
              </button>
            ))}
          </div>
        </div>
      ) : null}
      <div className="grid grid-cols-12 gap-4">
      <aside className="col-span-2 space-y-4">
        <ComponentPalette onAdd={addComponent} />
        <div className="space-y-2">
          <button onClick={save} disabled={busy}
            className="w-full btn-primary py-2 text-sm disabled:opacity-50">
            {busy ? "Saving..." : "Save draft"}
          </button>
          <button onClick={publish} disabled={busy}
            className="w-full border rounded py-2 text-sm">
            Publish
          </button>
          <button onClick={() => router.push(`/dashboards/${id}`)}
            className="w-full border rounded py-2 text-sm">
            Preview
          </button>
          <button onClick={shareDashboard}
            className="w-full border rounded py-2 text-sm">
            Share
          </button>
          <button onClick={removeDashboard}
            className="w-full border rounded py-2 text-sm text-red-600">
            Delete dashboard
          </button>
          {error && <div className="text-xs text-red-600">{error}</div>}
        </div>
      </aside>

      <section className="col-span-7 border rounded min-h-[600px] flex flex-col" style={{ background: "var(--bg-2)" }}>
        {/* Page tabs */}
        <div className="flex items-center gap-1 border-b px-2 py-1" style={{ background: "var(--panel)" }}>
          {pages.map((p) => (
            <div key={p.id} className="flex items-center gap-1">
              <button
                onClick={() => setActivePageId(p.id)}
                className={activePageId === p.id ? "btn-primary px-3 py-1 text-xs rounded" : "badge px-3 py-1 text-xs rounded hover:opacity-80"}
              >
                {p.title}
              </button>
              <button onClick={() => removePage(p.id)} className="text-gray-400 hover:text-red-500 text-xs">×</button>
            </div>
          ))}
          <button onClick={addPage} className="text-xs px-2 py-1 text-blue-600 hover:underline">+ Add page</button>
        </div>
        <div className="flex-1 p-2">
          <DashboardCanvas
            components={components}
            renders={renders}
            editable
            selectedId={selectedId}
            onSelect={setSelectedId}
            onLayoutChange={handleLayoutChange}
          />
          {components.length === 0 && (
            <div className="text-center text-gray-500 text-sm p-12">
              Drag from the palette on the left to start.
            </div>
          )}
        </div>
      </section>

      <aside className="col-span-3 app-card p-3 space-y-4 max-h-[80vh] overflow-auto">
        {selected ? (
          <>
            <PropertiesPanel
              component={selected}
              onChange={updateComponent}
              onDelete={deleteSelected}
            />
            {pages.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Page assignment</p>
                <select
                  value={pages.find((p) => p.component_ids.includes(selected.id))?.id ?? ""}
                  onChange={(e) => e.target.value && assignComponentToPage(selected.id, e.target.value)}
                  className="input-dark w-full text-xs"
                >
                  <option value="">No page (show on all)</option>
                  {pages.map((p) => (
                    <option key={p.id} value={p.id}>{p.title}</option>
                  ))}
                </select>
              </div>
            )}
            <DataBindingPanel component={selected} onChange={updateComponent} />
            <button onClick={() => renderOne(selected)}
              className="w-full border rounded py-1 text-xs">
              Preview this component
            </button>
          </>
        ) : (
          <div className="text-sm text-gray-500">Select a component to edit it.</div>
        )}
      </aside>
      </div>
    </div>
  );
}
