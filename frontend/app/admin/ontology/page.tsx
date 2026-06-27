"use client";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { apiFetch } from "@/lib/api";
import type { OntologyObjectOut, OntologyRelationshipOut } from "@/lib/ontology";
import type { Dataset } from "@/lib/types";
import { OntologyGraph } from "@/components/ontology/OntologyGraph";
import { ResourceHeader, ResourceToolbar } from "@/components/foundry/FoundryPrimitives";

type View = "graph" | "table";
type OntologyTab = "Discover" | "Proposals" | "History";
type Branch = {
  id: string;
  name: string;
  status: string;
  created_by: string | null;
  created_at: string;
  merged_at: string | null;
};
type AuditEvent = {
  id: string;
  event_type: string;
  resource_type: string | null;
  resource_id: string | null;
  input_summary: Record<string, unknown> | null;
  output_summary: Record<string, unknown> | null;
  created_at: string;
};

export default function AdminOntologyPage() {
  const [activeTab, setActiveTab] = useState<OntologyTab>("Discover");
  const [view, setView] = useState<View>("graph");
  const [objects, setObjects] = useState<OntologyObjectOut[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [history, setHistory] = useState<AuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [yamlText, setYamlText] = useState(YAML_EXAMPLE);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [rels, setRels] = useState<OntologyRelationshipOut[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [objForm, setObjForm] = useState({ type_name: "", dataset_id: "", primary_key: "id", display_name_column: "" });
  const [relForm, setRelForm] = useState({ source_type: "", target_type: "", name: "", cardinality: "one_to_many", source_key: "id", target_key: "id" });

  async function load() {
    try {
      const [objs, dss] = await Promise.all([
        apiFetch<OntologyObjectOut[]>("/ontology/objects"),
        apiFetch<Dataset[]>("/catalog/datasets"),
      ]);
      setObjects(objs);
      setDatasets(dss);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (activeTab === "Proposals") {
      apiFetch<Branch[]>("/platform/branches")
        .then((rows) => {
          setBranches(rows.filter((row) => row.status === "review" || row.status === "active"));
          setError(null);
        })
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    }
    if (activeTab === "History") {
      apiFetch<AuditEvent[]>("/admin/audit?limit=100")
        .then((rows) => {
          setHistory(rows.filter((row) => (row.resource_type ?? "").includes("ontology") || row.event_type.includes("ONTOLOGY")));
          setError(null);
        })
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    }
  }, [activeTab]);

  useEffect(() => {
    if (!selected) {
      setRels([]);
      return;
    }
    apiFetch<{ relationships: OntologyRelationshipOut[] }>(`/ontology/objects/${selected}`)
      .then((d) => setRels(d.relationships))
      .catch(() => setRels([]));
  }, [selected]);

  async function importYaml() {
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const out = await apiFetch<{ objects: number; relationships: number }>(
        "/admin/ontology/import-yaml",
        { method: "POST", body: JSON.stringify({ yaml: yamlText }) },
      );
      setMsg(`Imported ${out.objects} objects, ${out.relationships} relationships`);
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function removeObject(id: string) {
    if (!confirm("Delete object type?")) return;
    await apiFetch(`/admin/ontology/objects/${id}`, { method: "DELETE" });
    load();
  }

  async function createObject(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await apiFetch("/admin/ontology/objects", {
        method: "POST",
        body: JSON.stringify({
          type_name: objForm.type_name,
          dataset_id: objForm.dataset_id,
          primary_key: objForm.primary_key,
          display_name_column: objForm.display_name_column || null,
          properties: [],
          description: null,
        }),
      });
      setObjForm({ type_name: "", dataset_id: "", primary_key: "id", display_name_column: "" });
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  async function createRelationship(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await apiFetch("/admin/ontology/relationships", {
        method: "POST",
        body: JSON.stringify(relForm),
      });
      setRelForm({ source_type: "", target_type: "", name: "", cardinality: "one_to_many", source_key: "id", target_key: "id" });
      if (selected) {
        const d = await apiFetch<{ relationships: OntologyRelationshipOut[] }>(`/ontology/objects/${selected}`);
        setRels(d.relationships);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  async function removeRelationship(id: string) {
    if (!confirm("Delete relationship?")) return;
    await apiFetch(`/admin/ontology/relationships/${id}`, { method: "DELETE" });
    if (selected) {
      const d = await apiFetch<{ relationships: OntologyRelationshipOut[] }>(`/ontology/objects/${selected}`);
      setRels(d.relationships);
    }
  }

  return (
    <div className="space-y-6">
      <ResourceHeader
        eyebrow="Ontology Management"
        title="Discover Object Types"
        subtitle="Model business entities, properties, link types, action types, dependents, data mappings, and usage."
        tabs={[{ label: "Discover", id: "Discover" }, { label: "Proposals", id: "Proposals" }, { label: "History", id: "History" }]}
        activeTab={activeTab}
        onTabChange={(tab) => setActiveTab(tab as OntologyTab)}
        actions={<Segmented value={view} onChange={setView} />}
      />
      <ResourceToolbar>
        {["Object types", "Properties", "Link types", "Action types", "Functions", "Health issues", "Cleanup"].map((item) => <button key={item} className="btn-ghost">{item}</button>)}
      </ResourceToolbar>

      {activeTab === "Discover" ? (
      <>
      <div className="foundry-grid">
        {objects.slice(0, 6).map((o) => {
          const ds = datasets.find((d) => d.id === o.dataset_id);
          return (
            <button key={o.id} className="app-card" onClick={() => { setSelected(o.type_name); setView("table"); }} style={{ padding: 16, textAlign: "left" }}>
              <div className="badge badge-accent">Object type</div>
              <h3 style={{ margin: "10px 0 4px" }}>{o.type_name}</h3>
              <div style={{ color: "var(--muted)" }}>{ds?.name ?? o.dataset_id.slice(0, 8)}</div>
              <div className="stat-row" style={{ marginTop: 12 }}><span>{(o.properties ?? []).length} properties</span><span className="dot">•</span><span>Primary key {o.primary_key}</span></div>
            </button>
          );
        })}
      </div>

      {error && <div style={{ color: "var(--danger)", fontSize: 12 }}>{error}</div>}
      {msg && <div style={{ color: "var(--success)", fontSize: 12 }}>{msg}</div>}

      {view === "graph" ? <OntologyGraph /> : (
        <div className="grid grid-cols-2 gap-4">
          <section className="app-card overflow-hidden">
            <div className="section-header">
              <span className="section-header-title">Object types</span>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Dataset</th>
                  <th>PK</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {objects.length === 0 && (
                  <tr>
                    <td colSpan={4}>
                      <div className="empty-state">
                        <div className="empty-state-title">No objects yet</div>
                      </div>
                    </td>
                  </tr>
                )}
                {objects.map((o) => {
                  const ds = datasets.find((d) => d.id === o.dataset_id);
                  return (
                    <tr
                      key={o.id}
                      onClick={() => setSelected(o.type_name)}
                      style={{
                        cursor: "pointer",
                        background:
                          selected === o.type_name ? "var(--accent-soft)" : undefined,
                      }}
                    >
                      <td className="font-mono">{o.type_name}</td>
                      <td style={{ color: "var(--muted)" }}>
                        {ds?.name || o.dataset_id.slice(0, 8)}
                      </td>
                      <td className="font-mono" style={{ fontSize: 11.5 }}>
                        {o.primary_key}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            removeObject(o.id);
                          }}
                          style={{ color: "var(--danger)", fontSize: 12, background: "transparent", border: 0, cursor: "pointer" }}
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <section className="app-card overflow-hidden">
            <div className="section-header">
              <span className="section-header-title">{selected ? `Relationships from ${selected}` : "Relationships"}</span>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Target</th>
                  <th>Cardinality</th>
                  <th>Keys</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rels.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      <div className="empty-state">
                        <div className="empty-state-title">
                          {selected ? "No relationships" : "Pick an object"}
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
                {rels.map((r) => (
                  <tr key={r.id}>
                    <td className="font-mono">{r.name}</td>
                    <td className="font-mono">{r.target_type}</td>
                    <td>
                      <span className="badge">{r.cardinality}</span>
                    </td>
                    <td className="font-mono" style={{ fontSize: 11.5 }}>
                      {r.source_key} → {r.target_key}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <button type="button" style={{ color: "var(--danger)", background: "transparent", border: 0 }} onClick={() => removeRelationship(r.id)}>×</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <form onSubmit={createObject} className="app-card" style={{ padding: 14, display: "grid", gap: 8 }}>
          <div className="panel-heading" style={{ padding: 0, border: 0 }}>Create object type</div>
          <input className="input-dark" placeholder="Type name, e.g. Customer" value={objForm.type_name} onChange={(e) => setObjForm({ ...objForm, type_name: e.target.value })} required />
          <select className="input-dark" value={objForm.dataset_id} onChange={(e) => setObjForm({ ...objForm, dataset_id: e.target.value })} required>
            <option value="">Pick dataset</option>
            {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <input className="input-dark font-mono" placeholder="Primary key column" value={objForm.primary_key} onChange={(e) => setObjForm({ ...objForm, primary_key: e.target.value })} required />
          <input className="input-dark font-mono" placeholder="Display column (optional)" value={objForm.display_name_column} onChange={(e) => setObjForm({ ...objForm, display_name_column: e.target.value })} />
          <button className="btn-primary" disabled={busy}>Create object</button>
        </form>

        <form onSubmit={createRelationship} className="app-card" style={{ padding: 14, display: "grid", gap: 8 }}>
          <div className="panel-heading" style={{ padding: 0, border: 0 }}>Create relationship</div>
          <input className="input-dark" placeholder="Relationship name" value={relForm.name} onChange={(e) => setRelForm({ ...relForm, name: e.target.value })} required />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <select className="input-dark" value={relForm.source_type} onChange={(e) => setRelForm({ ...relForm, source_type: e.target.value })} required>
              <option value="">Source</option>
              {objects.map((o) => <option key={o.id} value={o.type_name}>{o.type_name}</option>)}
            </select>
            <select className="input-dark" value={relForm.target_type} onChange={(e) => setRelForm({ ...relForm, target_type: e.target.value })} required>
              <option value="">Target</option>
              {objects.map((o) => <option key={o.id} value={o.type_name}>{o.type_name}</option>)}
            </select>
          </div>
          <select className="input-dark" value={relForm.cardinality} onChange={(e) => setRelForm({ ...relForm, cardinality: e.target.value })}>
            <option value="one_to_one">one_to_one</option>
            <option value="one_to_many">one_to_many</option>
            <option value="many_to_one">many_to_one</option>
            <option value="many_to_many">many_to_many</option>
          </select>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <input className="input-dark font-mono" placeholder="Source key" value={relForm.source_key} onChange={(e) => setRelForm({ ...relForm, source_key: e.target.value })} required />
            <input className="input-dark font-mono" placeholder="Target key" value={relForm.target_key} onChange={(e) => setRelForm({ ...relForm, target_key: e.target.value })} required />
          </div>
          <button className="btn-primary" disabled={busy}>Create relationship</button>
        </form>
      </div>

      <section
        style={{
          background: "var(--panel)",
          border: "1px solid var(--line)",
          borderRadius: 3,
          padding: 14,
          display: "grid",
          gap: 8,
        }}
      >
        <div
          style={{
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--muted-2)",
          }}
        >
          Import YAML
        </div>
        <p style={{ color: "var(--muted)", fontSize: 11.5, margin: 0 }}>
          Each <code>table:</code> field must match a single dataset&apos;s{" "}
          <code>table_name</code>.
        </p>
        <textarea
          className="input-dark font-mono"
          value={yamlText}
          onChange={(e) => setYamlText(e.target.value)}
          style={{ fontSize: 12, lineHeight: 1.55, minHeight: 220 }}
        />
        <button
          type="button"
          className="btn-primary"
          onClick={importYaml}
          disabled={busy}
          style={{ justifySelf: "start" }}
        >
          {busy ? "Importing…" : "Import"}
        </button>
      </section>
      </>
      ) : activeTab === "Proposals" ? (
        <ProposalPanel branches={branches} />
      ) : (
        <HistoryPanel events={history} />
      )}
    </div>
  );
}

function Segmented({
  value,
  onChange,
}: {
  value: View;
  onChange: (v: View) => void;
}) {
  return (
    <div
      role="tablist"
      style={{
        display: "inline-flex",
        border: "1px solid var(--line)",
        borderRadius: 3,
        background: "var(--bg-2)",
        padding: 2,
      }}
    >
      {(["graph", "table"] as const).map((v) => (
        <button
          key={v}
          type="button"
          role="tab"
          aria-selected={value === v}
          onClick={() => onChange(v)}
          style={{
            padding: "5px 12px",
            fontSize: 11.5,
            fontWeight: 600,
            background: value === v ? "var(--accent-soft)" : "transparent",
            color: value === v ? "#fff" : "var(--muted)",
            border: 0,
            borderRadius: 3,
            cursor: "pointer",
            textTransform: "capitalize",
          }}
        >
          {v}
        </button>
      ))}
    </div>
  );
}

function ProposalPanel({ branches }: { branches: Branch[] }) {
  return (
    <section className="app-card overflow-hidden">
      <div className="section-header">
        <span className="section-header-title">Ontology proposals</span>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Branch</th>
            <th>Status</th>
            <th>Created</th>
            <th>Merged</th>
          </tr>
        </thead>
        <tbody>
          {branches.length === 0 ? (
            <tr>
              <td colSpan={4}>
                <div className="empty-state">
                  <div className="empty-state-title">No open proposals</div>
                </div>
              </td>
            </tr>
          ) : branches.map((branch) => (
            <tr key={branch.id}>
              <td className="font-mono">{branch.name}</td>
              <td><span className="badge">{branch.status}</span></td>
              <td style={{ color: "var(--muted)" }}>{new Date(branch.created_at).toLocaleString()}</td>
              <td style={{ color: "var(--muted)" }}>{branch.merged_at ? new Date(branch.merged_at).toLocaleString() : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function HistoryPanel({ events }: { events: AuditEvent[] }) {
  return (
    <section className="app-card overflow-hidden">
      <div className="section-header">
        <span className="section-header-title">Ontology history</span>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>Event</th>
            <th>Resource</th>
            <th>When</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          {events.length === 0 ? (
            <tr>
              <td colSpan={4}>
                <div className="empty-state">
                  <div className="empty-state-title">No ontology history yet</div>
                </div>
              </td>
            </tr>
          ) : events.map((event) => (
            <tr key={event.id}>
              <td className="font-mono">{event.event_type}</td>
              <td className="font-mono" style={{ fontSize: 11.5 }}>{event.resource_type ?? "—"}</td>
              <td style={{ color: "var(--muted)" }}>{new Date(event.created_at).toLocaleString()}</td>
              <td>
                <pre className="font-mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", margin: 0 }}>
                  {JSON.stringify(event.output_summary ?? event.input_summary ?? {}, null, 2)}
                </pre>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

const YAML_EXAMPLE = `objects:
  Customer:
    table: customers
    primary_key: id
    display_name: name
    properties:
      id: integer
      name: text
      country: text
    relationships:
      orders:
        target: Order
        type: one_to_many
        source_key: id
        target_key: customer_id
  Order:
    table: orders
    primary_key: id
    display_name: id
    properties:
      id: integer
      customer_id: integer
      amount: numeric
      status: text
`;
