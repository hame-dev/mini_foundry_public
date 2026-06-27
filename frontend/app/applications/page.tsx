"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { createApplication, listApplications, type Application } from "@/lib/applications";

export default function ApplicationsPage() {
  const [apps, setApps] = useState<Application[]>([]);
  const [name, setName] = useState("Operations app");
  const [objectType, setObjectType] = useState("Order");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      setApps(await listApplications());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load applications");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function createApp(e: React.FormEvent) {
    e.preventDefault();
    await createApplication({
      name,
      description: "Object-aware operational workspace",
      config: { layout: "default", variables: { selectedObject: null }, events: [] },
      pages: [
        {
          title: `${objectType} operations`,
          page_type: "object_workspace",
          object_type: objectType,
          config: {
            widgets: [
              { id: "object_list", type: "object_list", object_type: objectType },
              { id: "object_detail", type: "object_detail", source: "object_list.selectedObject" },
              { id: "action_form", type: "action_form", target: "object_list.selectedObject" },
              { id: "activity", type: "task_inbox", object_type: objectType },
            ],
          },
          position: 0,
        },
      ],
    });
    await load();
  }

  return (
    <div className="space-y-4">
      <form onSubmit={createApp} className="app-card p-4 grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-end">
        <label className="grid gap-1 text-sm">
          <span className="text-xs uppercase text-[var(--muted)]">Application</span>
          <input className="input-dark" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="grid gap-1 text-sm">
          <span className="text-xs uppercase text-[var(--muted)]">Object type</span>
          <input className="input-dark" value={objectType} onChange={(e) => setObjectType(e.target.value)} />
        </label>
        <button className="btn-primary px-4 py-2" type="submit">Create</button>
      </form>

      {error && <div className="app-card p-3 text-sm text-red-300">{error}</div>}
      {loading ? (
        <div className="app-card p-4 text-sm text-[var(--muted)]">Loading applications...</div>
      ) : apps.length === 0 ? (
        <div className="app-card p-4 text-sm text-[var(--muted)]">No applications yet.</div>
      ) : (
        <div className="grid gap-3">
          {apps.map((app) => (
            <section key={app.id} className="app-card p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="font-semibold">{app.name}</h2>
                  <p className="text-sm text-[var(--muted)]">{app.description || "Operational application"}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="topbar-pill">{app.status}</span>
                  <Link className="btn-primary text-xs" href={`/apps/builder/${app.id}`}>Open builder</Link>
                </div>
              </div>
              <div className="mt-3 grid gap-2">
                {app.pages.map((page) => (
                  <div key={page.id} className="rounded border border-[var(--line)] px-3 py-2 text-sm">
                    {page.title} · {page.page_type}{page.object_type ? ` · ${page.object_type}` : ""}
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
