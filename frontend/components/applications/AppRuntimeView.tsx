"use client";

import type { PublishedApp } from "@/lib/applications";
import { EmptyState } from "@/components/platform/States";

export function AppRuntimeView({ app }: { app: PublishedApp }) {
  const pages = app.pages ?? [];
  return (
    <div className="space-y-4">
      {app.notices?.length ? (
        <section className="app-card p-3">
          <h2 className="section-header-title mb-2">Runtime notices</h2>
          <ul className="grid gap-1 text-sm text-[var(--muted)]">
            {app.notices.map((notice, index) => (
              <li key={`${notice.type}-${index}`}>{notice.type.replace(/_/g, " ")}: {notice.reason.replace(/_/g, " ")}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {pages.length ? (
        pages.map((page, pageIndex) => {
          const widgets = Array.isArray(page.config?.widgets) ? page.config.widgets as Array<Record<string, unknown>> : [];
          return (
            <section key={page.id || `${page.title}-${pageIndex}`} className="app-card p-4">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line-soft)] pb-3">
                <div>
                  <h2 className="font-semibold">{page.title}</h2>
                  <p className="text-xs text-[var(--muted)]">{page.page_type}{page.object_type ? ` - ${page.object_type}` : ""}</p>
                </div>
                <span className="topbar-pill">{widgets.length} widgets</span>
              </div>
              {widgets.length ? (
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  {widgets.map((widget, index) => (
                    <div key={String(widget.id || index)} className="rounded border border-[var(--line-soft)] bg-[var(--panel-2)] p-3">
                      <div className="text-xs uppercase text-[var(--muted)]">{String(widget.type || "widget")}</div>
                      <div className="mt-1 font-semibold">{String(widget.id || `Widget ${index + 1}`)}</div>
                      <div className="mt-2 text-xs text-[var(--muted)]">
                        {String(widget.source || widget.object_type || widget.dataset_id || widget.saved_query_id || widget.action_id || "Runtime-governed widget")}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-3 text-sm text-[var(--muted)]">No visible widgets for this page.</p>
              )}
            </section>
          );
        })
      ) : (
        <EmptyState title="No visible pages" detail="No published pages are visible for your current permissions." />
      )}
    </div>
  );
}
