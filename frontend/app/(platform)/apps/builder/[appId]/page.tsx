"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getApplication, publishApplication, updateApplication, listAppVersions, getAppLineage, type AppPage, type Application, type AppVersion, type AppLineageEdge } from "@/lib/applications";
import { listActions, previewAction, type ActionPreview, type OntologyActionOut } from "@/lib/actions";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { useActiveBranch } from "@/lib/branchContext";

const WIDGETS = [
  { type: "object_list", label: "Object list", detail: "Browse governed ontology objects." },
  { type: "object_detail", label: "Object detail", detail: "Show selected object properties." },
  { type: "action_form", label: "Action form", detail: "Run approved writeback actions." },
  { type: "chart", label: "Chart", detail: "Bind analytical result data." },
  { type: "metric", label: "Metric", detail: "Show KPI values." },
  { type: "markdown", label: "Markdown", detail: "Operational notes and instructions." },
  { type: "task_inbox", label: "Task inbox", detail: "Show work items and approvals." },
];

function pageWidgets(page: AppPage): Array<Record<string, unknown>> {
  const widgets = page.config?.widgets;
  return Array.isArray(widgets) ? widgets as Array<Record<string, unknown>> : [];
}

export default function AppBuilderDetailPage({ params }: { params: Promise<{ appId: string }> }) {
  const { appId } = use(params);
  const [app, setApp] = useState<Application | null>(null);
  const [actions, setActions] = useState<OntologyActionOut[]>([]);
  const [selectedPageIndex, setSelectedPageIndex] = useState(0);
  const [selectedWidgetIndex, setSelectedWidgetIndex] = useState(0);
  const [actionPreview, setActionPreview] = useState<ActionPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [versions, setVersions] = useState<AppVersion[]>([]);
  const [lineage, setLineage] = useState<AppLineageEdge[]>([]);
  const { branchName, setBranchName } = useActiveBranch();

  async function loadVersionsAndLineage() {
    try {
      const [v, l] = await Promise.all([listAppVersions(appId), getAppLineage(appId)]);
      setVersions(v);
      setLineage(l);
    } catch {
      // non-fatal; panels stay empty
    }
  }

  async function load() {
    setLoading(true);
    try {
      const [nextApp, nextActions] = await Promise.all([getApplication(appId), listActions()]);
      setApp(nextApp);
      setActions(nextActions);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load application");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); void loadVersionsAndLineage(); }, [appId]); // eslint-disable-line react-hooks/exhaustive-deps

  const page = app?.pages[selectedPageIndex] || null;
  const widgets = useMemo(() => page ? pageWidgets(page) : [], [page]);
  const selectedWidget = widgets[selectedWidgetIndex] || null;
  const objectType = page?.object_type || String(selectedWidget?.object_type || "");
  const pageActions = actions.filter((action) => action.object_type == null || action.object_type === objectType);

  async function save(nextApp = app) {
    if (!nextApp) return;
    setSaving(true);
    try {
      const saved = await updateApplication(nextApp.id, {
        name: nextApp.name,
        description: nextApp.description,
        config: nextApp.config,
        pages: nextApp.pages.map((p, position) => ({ ...p, position })),
        branch_name: branchName || "main",
      });
      setApp(saved);
      setMessage("Saved draft.");
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save application");
    } finally {
      setSaving(false);
    }
  }

  async function publish() {
    if (!app) return;
    setSaving(true);
    try {
      setApp(await publishApplication(app.id, branchName || "main"));
      setMessage("Published.");
      setError(null);
      await loadVersionsAndLineage();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to publish application");
    } finally {
      setSaving(false);
    }
  }

  function addWidget(type: string) {
    if (!app || !page) return;
    const nextPages = app.pages.map((p, idx) => {
      if (idx !== selectedPageIndex) return p;
      const current = pageWidgets(p);
      return {
        ...p,
        config: {
          ...(p.config || {}),
          widgets: [
            ...current,
            { id: `${type}_${current.length + 1}`, type, object_type: p.object_type, source: "object_list.selectedObject" },
          ],
        },
      };
    });
    setApp({ ...app, pages: nextPages });
    setSelectedWidgetIndex(widgets.length);
  }

  async function previewFirstAction() {
    const action = pageActions[0];
    if (!action) return;
    try {
      setActionPreview(await previewAction(action.name, { object_type: objectType, object_id: "{{selectedObject.id}}" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to preview action");
    }
  }

  if (loading) return <LoadingState label="Loading app builder..." />;
  if (error && !app) return <ErrorState message={error} />;
  if (!app) return <EmptyState title="Application not found" detail="The application resource could not be loaded." />;

  return (
    <div className="space-y-4">
      <ResourceHeader
        title={app.name}
        type="Operational app"
        status={app.status}
        actions={(
          <div className="flex flex-wrap gap-2">
            <input className="input-dark h-8 w-28 text-xs" value={branchName} onChange={(event) => setBranchName(event.target.value)} aria-label="Branch name" />
            <button className="btn-ghost text-xs" disabled={saving} onClick={() => void save()}>{saving ? "Saving..." : "Save"}</button>
            <Link className="btn-ghost text-xs" href={`/apps/builder/${app.id}/preview`}>Preview</Link>
            <Link className="btn-primary text-xs" href={`/apps/builder/${app.id}/publish`}>Publish review</Link>
            <button className="btn-ghost text-xs" disabled={saving} onClick={() => void publish()}>Quick publish</button>
            <Link className="btn-ghost text-xs" href={`/apps/published/${app.id}`}>Published view</Link>
          </div>
        )}
      />
      {message ? <div className="app-card p-3 text-sm text-[var(--success)]">{message}</div> : null}
      {error ? <div className="app-card p-3 text-sm text-[var(--danger)]">{error}</div> : null}

      <div className="grid gap-3 lg:grid-cols-[220px_minmax(0,1fr)_320px]">
        <aside className="app-card p-3 space-y-4">
          <section>
            <h2 className="section-header-title mb-2">Page tree</h2>
            <div className="grid gap-1">
              {app.pages.map((p, idx) => (
                <button
                  key={p.id || `${p.title}-${idx}`}
                  className={idx === selectedPageIndex ? "btn-primary text-xs justify-start" : "btn-ghost text-xs justify-start"}
                  onClick={() => { setSelectedPageIndex(idx); setSelectedWidgetIndex(0); }}
                >
                  {p.title}
                </button>
              ))}
            </div>
          </section>
          <section>
            <h2 className="section-header-title mb-2">Widget palette</h2>
            <div className="grid gap-2">
              {WIDGETS.map((widget) => (
                <button key={widget.type} className="text-left rounded border p-2 hover:bg-[var(--panel-2)]" style={{ borderColor: "var(--line)" }} onClick={() => addWidget(widget.type)}>
                  <span className="block text-xs font-semibold">{widget.label}</span>
                  <span className="block text-[11px] text-[var(--muted)]">{widget.detail}</span>
                </button>
              ))}
            </div>
          </section>
        </aside>

        <main className="app-card p-3 min-h-[560px]">
          <div className="flex items-center justify-between border-b pb-3 mb-3" style={{ borderColor: "var(--line)" }}>
            <div>
              <h2 className="font-semibold">{page?.title || "Untitled page"}</h2>
              <p className="text-xs text-[var(--muted)]">Canvas preview runs as the current user and keeps action execution behind confirmation.</p>
            </div>
            <span className="topbar-pill">{objectType || "No object type"}</span>
          </div>
          {widgets.length === 0 ? (
            <EmptyState title="No widgets" detail="Use the widget palette to add object, action, chart, metric, markdown, and task widgets." />
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {widgets.map((widget, idx) => (
                <button
                  key={String(widget.id || idx)}
                  onClick={() => setSelectedWidgetIndex(idx)}
                  className="text-left rounded border p-3 min-h-28"
                  style={{
                    borderColor: idx === selectedWidgetIndex ? "var(--accent)" : "var(--line)",
                    background: idx === selectedWidgetIndex ? "var(--accent-soft)" : "var(--panel-2)",
                  }}
                >
                  <span className="block text-xs uppercase text-[var(--muted)]">{String(widget.type || "widget")}</span>
                  <span className="block mt-1 font-semibold">{String(widget.id || `Widget ${idx + 1}`)}</span>
                  <span className="block mt-2 text-xs text-[var(--muted)]">
                    {widget.type === "action_form"
                      ? `${pageActions.length} governed actions available`
                      : String(widget.source || widget.object_type || "Configure in properties")}
                  </span>
                </button>
              ))}
            </div>
          )}
        </main>

        <aside className="space-y-3">
          <section className="app-card p-3">
            <h2 className="section-header-title mb-2">Properties</h2>
            {selectedWidget ? (
              <dl className="grid gap-2 text-xs">
                <div><dt className="text-[var(--muted)]">Widget</dt><dd className="font-mono">{String(selectedWidget.id || selectedWidget.type)}</dd></div>
                <div><dt className="text-[var(--muted)]">Type</dt><dd>{String(selectedWidget.type)}</dd></div>
                <div><dt className="text-[var(--muted)]">Object binding</dt><dd>{objectType || "Not configured"}</dd></div>
              </dl>
            ) : <p className="text-xs text-[var(--muted)]">Select a widget to edit properties.</p>}
          </section>

          <section className="app-card p-3">
            <h2 className="section-header-title mb-2">Data binding</h2>
            <p className="text-xs text-[var(--muted)]">Bindings are stored in the application page spec and resolved by backend-governed object, query, and action APIs.</p>
          </section>

          <section className="app-card p-3">
            <h2 className="section-header-title mb-2">Variables</h2>
            <pre className="text-xs overflow-auto rounded p-2" style={{ background: "var(--panel-2)" }}>{JSON.stringify(app.config?.variables || {}, null, 2)}</pre>
          </section>

          <section className="app-card p-3">
            <div className="flex items-center justify-between gap-2 mb-2">
              <h2 className="section-header-title">Events & actions</h2>
              <button className="btn-ghost text-xs" disabled={!pageActions.length} onClick={() => void previewFirstAction()}>Preview</button>
            </div>
            {pageActions.length ? (
              <div className="grid gap-2">
                {pageActions.slice(0, 5).map((action) => (
                  <div key={action.id} className="rounded border p-2 text-xs" style={{ borderColor: "var(--line)" }}>
                    <div className="font-semibold">{action.name}</div>
                    <div className="text-[var(--muted)]">{action.approval_required ? "Approval required" : "Direct action"} · {action.can_run === false ? action.permission_explanation : "Runnable if backend validation passes"}</div>
                  </div>
                ))}
              </div>
            ) : <p className="text-xs text-[var(--muted)]">No actions found for this object type.</p>}
            {actionPreview ? (
              <div className="mt-3 rounded border p-2 text-xs" style={{ borderColor: "var(--line)", background: "var(--panel-2)" }}>
                <div className="font-semibold">Side-effect preview</div>
                <div className="mt-1">{actionPreview.approval_required ? "Approval required" : "No approval required"}</div>
                <div className="mt-2 grid gap-1">
                  {actionPreview.side_effects.map((effect, idx) => (
                    <span key={idx} className="font-mono">{String(effect.type)} · {String(effect.object_type || effect.workflow_key || "target")}</span>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        </aside>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className="app-card p-3">
          <h2 className="section-header-title mb-2">Version history</h2>
          {versions.length ? (
            <ul className="space-y-1 text-sm">
              {versions.map((v) => (
                <li key={v.id} className="flex items-center justify-between gap-3 border-t border-[var(--line-soft)] py-2 first:border-0">
                  <span className="font-medium">v{v.version_number}</span>
                  <span className="text-xs text-[var(--muted)]">
                    {v.published_at ? new Date(v.published_at).toLocaleString() : new Date(v.created_at).toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--muted)]">No published versions yet. Publish to create the first immutable version.</p>
          )}
        </section>

        <section className="app-card p-3">
          <h2 className="section-header-title mb-2">Lineage (upstream)</h2>
          {lineage.length ? (
            <ul className="space-y-1 text-sm">
              {lineage.map((e, i) => (
                <li key={i} className="flex items-center justify-between gap-3 border-t border-[var(--line-soft)] py-2 first:border-0">
                  <span className="truncate">{e.source_name || e.source_resource_id}</span>
                  <span className="text-xs text-[var(--muted)]">{e.source_type} · {e.edge_type}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--muted)]">No upstream object types or datasets recorded. Publish to capture lineage.</p>
          )}
        </section>
      </div>
    </div>
  );
}
