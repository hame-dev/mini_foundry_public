"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import AiDashboardPrompt from "@/components/ai/AiDashboardPrompt";
import type { DashboardDetail, DashboardLayout } from "@/lib/dashboards";
import { ModuleCard, ResourceHeader } from "@/components/foundry/FoundryPrimitives";

const templates = [
  { title: "Blank module", kind: "workshop", icon: "+", description: "Start an operational app canvas from scratch." },
  { title: "Inbox template", kind: "workshop", icon: "▤", description: "Object table with filters and action panel." },
  { title: "Map template", kind: "workshop", icon: "⌖", description: "Geospatial object workflow with linked results." },
  { title: "Metrics template", kind: "workshop", icon: "%", description: "Operational KPIs with action widgets." },
  { title: "Contour dashboard", kind: "contour", icon: "xy", description: "Dataset analysis dashboard with charts and tables." },
  { title: "Quiver dashboard", kind: "quiver", icon: "obj", description: "Ontology-centered object and time-series dashboard." },
] as const;

export default function NewDashboardPage() {
  const router = useRouter();
  const [title, setTitle] = useState("Untitled module");
  const [description, setDescription] = useState("");
  const [aiResult, setAiResult] = useState<{ title: string; description: string | null; layout: DashboardLayout } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create(kind: "contour" | "workshop" | "quiver", templateTitle?: string) {
    setBusy(true); setError(null);
    try {
      const d = await apiFetch<DashboardDetail>("/dashboards", {
        method: "POST",
        body: JSON.stringify({
          title: templateTitle ? `${templateTitle}` : title,
          description: description || templateTitle || null,
          dashboard_kind: kind,
          layout: { version: 1, components: [], filters: [] },
        }),
      });
      router.push(`/dashboards/${d.id}/edit`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveAi() {
    if (!aiResult) return;
    setBusy(true); setError(null);
    try {
      const d = await apiFetch<DashboardDetail>("/dashboards", {
        method: "POST",
        body: JSON.stringify({
          title: aiResult.title,
          description: aiResult.description,
          dashboard_kind: "contour",
          layout: aiResult.layout,
        }),
      });
      router.push(`/dashboards/${d.id}/edit`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <ResourceHeader
        eyebrow="Workshop / Dashboards"
        title="Create New Module"
        subtitle="Choose a dataset analysis dashboard, ontology operational app, or object dashboard template."
        tabs={[{ label: "Templates", id: "Templates" }, { label: "AI generated", id: "AI generated" }, { label: "Recent", id: "Recent" }]}
        activeTab="Templates"
        actions={<button className="btn-primary" disabled={busy} onClick={() => create("workshop")}>Create blank</button>}
      />
      {error ? <div className="app-card" style={{ padding: 12, color: "var(--danger)" }}>Load failed: {error}</div> : null}

      <section className="app-card" style={{ padding: 14 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Module title" style={{ padding: "8px 10px" }} />
          <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description" style={{ padding: "8px 10px" }} />
        </div>
      </section>

      <div className="foundry-grid">
        {templates.map((template) => (
          <button key={template.title} disabled={busy} onClick={() => create(template.kind, template.title)} style={{ textAlign: "left", border: 0, background: "transparent", padding: 0 }}>
            <ModuleCard title={template.title} subtitle={template.description} icon={template.icon} />
          </button>
        ))}
      </div>

      <div className="app-card" style={{ padding: 14 }}>
        <div className="section-header" style={{ margin: "-14px -14px 14px" }}>
          <div className="section-header-title">AI module generator</div>
        </div>
        <AiDashboardPrompt onResult={setAiResult} />
      </div>

      {aiResult && (
        <div className="app-card" style={{ padding: 14, display: "grid", gap: 8 }}>
          <h2>{aiResult.title}</h2>
          {aiResult.description ? <p style={{ color: "var(--muted)" }}>{aiResult.description}</p> : null}
          <span className="badge">{aiResult.layout.components.length} widgets</span>
          <button onClick={saveAi} disabled={busy} className="btn-primary" style={{ justifySelf: "start" }}>
            {busy ? "Saving..." : "Save and open in builder"}
          </button>
        </div>
      )}
    </div>
  );
}
