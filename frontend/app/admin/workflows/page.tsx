"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { OntologyActionOut } from "@/lib/actions";

type Workflow = { name: string; sync: boolean };
type ValidationRule = { property: string; type: string; pattern?: string; min?: number; max?: number; values?: string };

export default function AdminWorkflowsPage() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [actions, setActions] = useState<OntologyActionOut[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [workflowKey, setWorkflowKey] = useState("");
  const [objectType, setObjectType] = useState("");
  const [description, setDescription] = useState("");

  const [grantActionId, setGrantActionId] = useState("");
  const [grantUserId, setGrantUserId] = useState("");

  // Validation + webhook editor state
  const [editActionId, setEditActionId] = useState<string>("");
  const [rules, setRules] = useState<ValidationRule[]>([]);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const [editMsg, setEditMsg] = useState<string | null>(null);

  async function load() {
    try {
      const [wf, acts] = await Promise.all([
        apiFetch<{ workflows: Workflow[] }>("/admin/workflows"),
        apiFetch<OntologyActionOut[]>("/admin/ontology/actions"),
      ]);
      setWorkflows(wf.workflows);
      setActions(acts);
      if (!workflowKey && wf.workflows.length) setWorkflowKey(wf.workflows[0].name);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => { load(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  function selectActionForEdit(id: string) {
    setEditActionId(id);
    setEditMsg(null);
    const a = actions.find((x) => x.id === id);
    if (!a) return;
    setRules(((a as any).validation_rules || []).map((r: any) => ({
      property: r.property || "",
      type: r.type || "required",
      pattern: r.pattern || "",
      min: r.min,
      max: r.max,
      values: r.values ? r.values.join(", ") : "",
    })));
    setWebhookUrl((a as any).webhook_url || "");
    setWebhookSecret("");
  }

  async function saveActionConfig(e: React.FormEvent) {
    e.preventDefault();
    if (!editActionId) return;
    setEditBusy(true);
    setEditMsg(null);
    try {
      const parsedRules = rules.map((r) => {
        const rule: Record<string, unknown> = { property: r.property, type: r.type };
        if (r.type === "regex" && r.pattern) rule.pattern = r.pattern;
        if (r.type === "range") { if (r.min != null) rule.min = r.min; if (r.max != null) rule.max = r.max; }
        if (r.type === "enum" && r.values) rule.values = r.values.split(",").map((v) => v.trim());
        return rule;
      });
      await apiFetch(`/admin/ontology/actions/${editActionId}`, {
        method: "PATCH",
        body: JSON.stringify({
          validation_rules: parsedRules.length > 0 ? parsedRules : null,
          webhook_url: webhookUrl || null,
          webhook_secret: webhookSecret || undefined,
        }),
      });
      setEditMsg("Saved.");
      load();
    } catch (e: unknown) {
      setEditMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setEditBusy(false);
    }
  }

  async function createAction(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiFetch("/admin/ontology/actions", {
        method: "POST",
        body: JSON.stringify({
          name, workflow_key: workflowKey,
          object_type: objectType || null,
          description: description || null,
          input_schema: null, enabled: true,
        }),
      });
      setName(""); setObjectType(""); setDescription("");
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function grant(e: React.FormEvent) {
    e.preventDefault();
    try {
      await apiFetch("/admin/ontology/actions/grant", {
        method: "POST",
        body: JSON.stringify({
          action_id: grantActionId, subject_type: "user",
          subject_id: grantUserId, can_run: true,
        }),
      });
      setGrantUserId("");
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function addRule() {
    setRules([...rules, { property: "", type: "required" }]);
  }
  function removeRule(i: number) {
    setRules(rules.filter((_, idx) => idx !== i));
  }
  function updateRule(i: number, patch: Partial<ValidationRule>) {
    setRules(rules.map((r, idx) => idx === i ? { ...r, ...patch } : r));
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Workflows &amp; Actions</h1>
      {error && <div className="text-red-600 text-sm">{error}</div>}

      <section className="app-card p-4 space-y-2">
        <h2 className="section-header-title">Registered workflows</h2>
        <ul className="text-xs space-y-1">
          {workflows.map((w) => (
            <li key={w.name} className="flex gap-3">
              <code style={{ color: "var(--text)" }}>{w.name}</code>
              <span className="badge">{w.sync ? "sync" : "async"}</span>
            </li>
          ))}
          {workflows.length === 0 && <li style={{ color: "var(--muted)" }}>No workflows registered.</li>}
        </ul>
      </section>

      <form onSubmit={createAction} className="app-card p-4 grid grid-cols-5 gap-2 items-end">
        <div>
          <label className="block text-xs mb-1" style={{ color: "var(--muted)" }}>Action name</label>
          <input className="input-dark" required value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs mb-1" style={{ color: "var(--muted)" }}>Workflow</label>
          <select className="input-dark" value={workflowKey} onChange={(e) => setWorkflowKey(e.target.value)}>
            {workflows.map((w) => <option key={w.name}>{w.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs mb-1" style={{ color: "var(--muted)" }}>Object type (optional)</label>
          <input className="input-dark" value={objectType} onChange={(e) => setObjectType(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs mb-1" style={{ color: "var(--muted)" }}>Description</label>
          <input className="input-dark" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <button className="btn-primary text-sm">Create action</button>
      </form>

      <section className="app-card overflow-hidden">
        <div className="section-header">
          <span className="section-header-title">Actions</span>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Workflow</th>
              <th>Object type</th>
              <th>Enabled</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {actions.map((a) => (
              <tr key={a.id} style={editActionId === a.id ? { background: "var(--accent-soft)" } : {}}>
                <td className="font-mono">{a.name}</td>
                <td className="font-mono">{a.workflow_key}</td>
                <td>{a.object_type || "—"}</td>
                <td>
                  {a.enabled
                    ? <span className="badge badge-success">yes</span>
                    : <span className="badge">no</span>
                  }
                </td>
                <td>
                  <button onClick={() => selectActionForEdit(a.id)} style={{ color: "var(--accent)" }} className="hover:underline text-xs">
                    Edit rules & webhook
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Validation rules + webhook editor */}
      {editActionId && (
        <form onSubmit={saveActionConfig} className="app-card p-4 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
              Validation rules & webhook — {actions.find((a) => a.id === editActionId)?.name}
            </h2>
            <button type="button" onClick={() => setEditActionId("")} style={{ color: "var(--muted-2)" }} className="text-xs hover:opacity-80">×</button>
          </div>

          {/* Validation rules */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="section-header-title">Validation Rules</span>
              <button type="button" onClick={addRule} style={{ color: "var(--accent)" }} className="text-xs hover:underline">+ Add rule</button>
            </div>
            {rules.length === 0 && <p className="text-xs" style={{ color: "var(--muted-2)" }}>No rules configured.</p>}
            {rules.map((rule, i) => (
              <div key={i} className="flex gap-2 items-start p-2 rounded" style={{ background: "var(--panel-2)", border: "1px solid var(--line)" }}>
                <input
                  className="input-dark font-mono"
                  style={{ width: 120, fontSize: 11 }}
                  placeholder="property"
                  value={rule.property}
                  onChange={(e) => updateRule(i, { property: e.target.value })}
                />
                <select
                  className="input-dark"
                  style={{ fontSize: 11, width: "auto" }}
                  value={rule.type}
                  onChange={(e) => updateRule(i, { type: e.target.value })}
                >
                  <option value="required">required</option>
                  <option value="regex">regex</option>
                  <option value="range">range</option>
                  <option value="enum">enum</option>
                </select>
                {rule.type === "regex" && (
                  <input
                    className="input-dark font-mono flex-1"
                    style={{ fontSize: 11 }}
                    placeholder="pattern, e.g. ^[^@]+@[^@]+$"
                    value={rule.pattern || ""}
                    onChange={(e) => updateRule(i, { pattern: e.target.value })}
                  />
                )}
                {rule.type === "range" && (
                  <>
                    <input
                      className="input-dark"
                      style={{ width: 72, fontSize: 11 }}
                      placeholder="min"
                      type="number"
                      value={rule.min ?? ""}
                      onChange={(e) => updateRule(i, { min: e.target.value ? Number(e.target.value) : undefined })}
                    />
                    <input
                      className="input-dark"
                      style={{ width: 72, fontSize: 11 }}
                      placeholder="max"
                      type="number"
                      value={rule.max ?? ""}
                      onChange={(e) => updateRule(i, { max: e.target.value ? Number(e.target.value) : undefined })}
                    />
                  </>
                )}
                {rule.type === "enum" && (
                  <input
                    className="input-dark flex-1"
                    style={{ fontSize: 11 }}
                    placeholder="value1, value2, value3"
                    value={rule.values || ""}
                    onChange={(e) => updateRule(i, { values: e.target.value })}
                  />
                )}
                <button type="button" onClick={() => removeRule(i)} style={{ color: "var(--danger)" }} className="text-xs px-1 hover:opacity-80">×</button>
              </div>
            ))}
          </div>

          {/* Webhook */}
          <div className="space-y-2">
            <span className="section-header-title">Webhook</span>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs mb-1" style={{ color: "var(--muted)" }}>Webhook URL</label>
                <input
                  className="input-dark font-mono"
                  style={{ fontSize: 11 }}
                  placeholder="https://example.com/webhook"
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                />
              </div>
              <div>
                <label className="block text-xs mb-1" style={{ color: "var(--muted)" }}>Secret (leave blank to keep existing)</label>
                <input
                  className="input-dark font-mono"
                  style={{ fontSize: 11 }}
                  type="password"
                  placeholder="••••••••"
                  value={webhookSecret}
                  onChange={(e) => setWebhookSecret(e.target.value)}
                />
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button className="btn-primary text-sm disabled:opacity-50" disabled={editBusy}>
              {editBusy ? "Saving…" : "Save"}
            </button>
            {editMsg && (
              <span className="text-xs" style={{ color: editMsg === "Saved." ? "var(--success)" : "var(--danger)" }}>
                {editMsg}
              </span>
            )}
          </div>
        </form>
      )}

      <form onSubmit={grant} className="app-card p-4 grid grid-cols-3 gap-2 items-end">
        <div>
          <label className="block text-xs mb-1" style={{ color: "var(--muted)" }}>Action</label>
          <select className="input-dark" value={grantActionId} onChange={(e) => setGrantActionId(e.target.value)} required>
            <option value="">—</option>
            {actions.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs mb-1" style={{ color: "var(--muted)" }}>User UUID</label>
          <input className="input-dark font-mono" required value={grantUserId} onChange={(e) => setGrantUserId(e.target.value)} />
        </div>
        <button className="btn-primary text-sm">Grant can_run</button>
      </form>
    </div>
  );
}
