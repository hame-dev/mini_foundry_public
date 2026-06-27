"use client";

import { useEffect, useMemo, useState } from "react";
import type { PipelineNode } from "@/lib/pipelines";
import { NODE_LABELS } from "@/lib/pipelines";
import type { Dataset } from "@/lib/types";
import type { MLModel, MLModelVersion } from "@/lib/models";
import { apiFetch } from "@/lib/api";

type Props = {
  node: PipelineNode;
  datasets: Dataset[];
  onChange: (patch: Partial<PipelineNode>) => void;
  onDelete: () => void;
};

export function NodeInspector({ node, datasets, onChange, onDelete }: Props) {
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Header label={`${NODE_LABELS[node.node_type]} node`} onDelete={onDelete} />

      {node.node_type === "source" && (
        <SourceEditor node={node} datasets={datasets} onChange={onChange} />
      )}
      {node.node_type === "filter" && <FilterEditor node={node} onChange={onChange} />}
      {node.node_type === "formula" && <FormulaEditor node={node} onChange={onChange} />}
      {node.node_type === "select" && <SelectEditor node={node} onChange={onChange} />}
      {node.node_type === "trained_model" && <TrainedModelEditor node={node} onChange={onChange} />}
      {node.node_type === "join" && <JoinEditor node={node} onChange={onChange} />}
      {node.node_type === "union" && <UnionEditor node={node} onChange={onChange} />}
      {node.node_type === "output" && <OutputEditor node={node} onChange={onChange} />}
    </div>
  );
}

function Header({ label, onDelete }: { label: string; onDelete: () => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--muted-2)",
        }}
      >
        Selected
      </span>
      <button type="button" className="btn-ghost" onClick={onDelete}>
        Delete
      </button>
    </div>
  );
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label style={{ display: "grid", gap: 5 }}>
      <span
        style={{
          fontSize: 10.5,
          fontWeight: 600,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          color: "var(--muted)",
        }}
      >
        {label}
      </span>
      {children}
      {hint ? <span style={{ fontSize: 11, color: "var(--muted-2)" }}>{hint}</span> : null}
    </label>
  );
}

function SourceEditor({
  node,
  datasets,
  onChange,
}: {
  node: PipelineNode;
  datasets: Dataset[];
  onChange: (patch: Partial<PipelineNode>) => void;
}) {
  const cfg = node.config as { dataset_id?: string };
  return (
    <Field label="Dataset">
      <select
        value={cfg.dataset_id ?? ""}
        onChange={(e) =>
          onChange({ config: { ...node.config, dataset_id: e.target.value || undefined } })
        }
        style={{ padding: "7px 8px", fontSize: 12 }}
      >
        <option value="">— pick a dataset —</option>
        {datasets.map((d) => (
          <option key={d.id} value={d.id}>
            {d.name} ({d.schema_name}.{d.table_name})
          </option>
        ))}
      </select>
    </Field>
  );
}

function FilterEditor({ node, onChange }: { node: PipelineNode; onChange: (p: Partial<PipelineNode>) => void }) {
  const cfg = node.config as { where?: string };
  return (
    <Field
      label="WHERE clause"
      hint="SQL boolean expression. Available columns come from the input node."
    >
      <textarea
        rows={4}
        value={cfg.where ?? ""}
        onChange={(e) => onChange({ config: { ...node.config, where: e.target.value } })}
        placeholder="status = 'active' AND amount > 100"
        className="font-mono"
        style={{ padding: 8, fontSize: 12, lineHeight: 1.5 }}
      />
    </Field>
  );
}

function FormulaEditor({ node, onChange }: { node: PipelineNode; onChange: (p: Partial<PipelineNode>) => void }) {
  const cfg = node.config as { columns?: { name: string; expr: string }[] };
  const cols = cfg.columns ?? [];
  const update = (next: { name: string; expr: string }[]) =>
    onChange({ config: { ...node.config, columns: next } });
  return (
    <Field label="Computed columns" hint="Each row appears as: alias = SQL expression.">
      <div style={{ display: "grid", gap: 8 }}>
        {cols.map((c, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "120px 1fr auto", gap: 6 }}>
            <input
              value={c.name}
              onChange={(e) => {
                const next = [...cols];
                next[i] = { ...next[i], name: e.target.value };
                update(next);
              }}
              placeholder="alias"
              style={{ padding: "6px 8px", fontSize: 12 }}
            />
            <input
              value={c.expr}
              onChange={(e) => {
                const next = [...cols];
                next[i] = { ...next[i], expr: e.target.value };
                update(next);
              }}
              placeholder="amount * 1.2"
              className="font-mono"
              style={{ padding: "6px 8px", fontSize: 12 }}
            />
            <button
              type="button"
              className="btn-ghost"
              onClick={() => update(cols.filter((_, j) => j !== i))}
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn-ghost"
          onClick={() => update([...cols, { name: "", expr: "" }])}
          style={{ justifySelf: "start" }}
        >
          + Add column
        </button>
      </div>
    </Field>
  );
}

function SelectEditor({ node, onChange }: { node: PipelineNode; onChange: (p: Partial<PipelineNode>) => void }) {
  const cfg = node.config as { columns?: string[]; rename?: Record<string, string> };
  return (
    <>
      <Field label="Columns" hint="Comma-separated. Leave empty to select all.">
        <input
          value={(cfg.columns ?? []).join(", ")}
          onChange={(e) => {
            const next = e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean);
            onChange({ config: { ...node.config, columns: next } });
          }}
          placeholder="id, name, created_at"
          className="font-mono"
          style={{ padding: "7px 8px", fontSize: 12 }}
        />
      </Field>
      <Field
        label="Renames"
        hint="JSON object, e.g. { &quot;created_at&quot;: &quot;ts&quot; }."
      >
        <textarea
          rows={3}
          value={JSON.stringify(cfg.rename ?? {}, null, 2)}
          onChange={(e) => {
            try {
              const obj = JSON.parse(e.target.value || "{}");
              onChange({ config: { ...node.config, rename: obj } });
            } catch {
              // ignore invalid until they fix it
            }
          }}
          className="font-mono"
          style={{ padding: 8, fontSize: 12, lineHeight: 1.5 }}
        />
      </Field>
    </>
  );
}

function JoinEditor({ node, onChange }: { node: PipelineNode; onChange: (p: Partial<PipelineNode>) => void }) {
  const cfg = node.config as {
    join_type?: string;
    left_keys?: string[];
    right_keys?: string[];
    suggested_from_ontology_relationship_id?: string | null;
  };
  const pairs = useMemo(() => {
    const lk = cfg.left_keys ?? [];
    const rk = cfg.right_keys ?? [];
    const len = Math.max(lk.length, rk.length, 1);
    return Array.from({ length: len }, (_, i) => ({ l: lk[i] ?? "", r: rk[i] ?? "" }));
  }, [cfg.left_keys, cfg.right_keys]);
  const updatePairs = (next: { l: string; r: string }[]) =>
    onChange({
      config: {
        ...node.config,
        left_keys: next.map((p) => p.l),
        right_keys: next.map((p) => p.r),
        suggested_from_ontology_relationship_id: null,
      },
    });
  return (
    <>
      {cfg.suggested_from_ontology_relationship_id ? (
        <div
          style={{
            padding: "8px 10px",
            border: "1px solid var(--accent-line)",
            background: "var(--accent-soft)",
            borderRadius: 3,
            fontSize: 11.5,
            color: "#bcd0ff",
          }}
        >
          Auto-joined from the ontology. Editing keys will detach this link.
        </div>
      ) : null}
      <Field label="Join type">
        <select
          value={cfg.join_type ?? "inner"}
          onChange={(e) => onChange({ config: { ...node.config, join_type: e.target.value } })}
          style={{ padding: "7px 8px", fontSize: 12 }}
        >
          <option value="inner">INNER</option>
          <option value="left">LEFT</option>
          <option value="right">RIGHT</option>
          <option value="full">FULL</option>
        </select>
      </Field>
      <Field label="Key pairs" hint="left column = right column">
        <div style={{ display: "grid", gap: 6 }}>
          {pairs.map((p, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 16px 1fr auto", gap: 6, alignItems: "center" }}>
              <input
                value={p.l}
                onChange={(e) => {
                  const next = [...pairs];
                  next[i] = { ...next[i], l: e.target.value };
                  updatePairs(next);
                }}
                placeholder="left.id"
                className="font-mono"
                style={{ padding: "6px 8px", fontSize: 12 }}
              />
              <span style={{ textAlign: "center", color: "var(--muted-2)" }}>=</span>
              <input
                value={p.r}
                onChange={(e) => {
                  const next = [...pairs];
                  next[i] = { ...next[i], r: e.target.value };
                  updatePairs(next);
                }}
                placeholder="right.left_id"
                className="font-mono"
                style={{ padding: "6px 8px", fontSize: 12 }}
              />
              <button
                type="button"
                className="btn-ghost"
                onClick={() => updatePairs(pairs.filter((_, j) => j !== i))}
              >
                ×
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn-ghost"
            onClick={() => updatePairs([...pairs, { l: "", r: "" }])}
            style={{ justifySelf: "start" }}
          >
            + Add key pair
          </button>
        </div>
      </Field>
    </>
  );
}

function UnionEditor({ node, onChange }: { node: PipelineNode; onChange: (p: Partial<PipelineNode>) => void }) {
  const cfg = node.config as { distinct?: boolean };
  return (
    <Field label="Mode">
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5 }}>
        <input
          type="checkbox"
          checked={Boolean(cfg.distinct)}
          onChange={(e) => onChange({ config: { ...node.config, distinct: e.target.checked } })}
        />
        Drop duplicates (UNION instead of UNION ALL)
      </label>
    </Field>
  );
}

function OutputEditor({ node, onChange }: { node: PipelineNode; onChange: (p: Partial<PipelineNode>) => void }) {
  const cfg = node.config as { name?: string; description?: string; materialize?: "view" | "table" | "parquet" };
  return (
    <>
      <Field label="Output name" hint="Used as the Dataset name in the catalog.">
        <input
          value={cfg.name ?? ""}
          onChange={(e) => onChange({ config: { ...node.config, name: e.target.value } })}
          placeholder="my_pipeline_output"
          style={{ padding: "7px 8px", fontSize: 12 }}
        />
      </Field>
      <Field label="Description">
        <textarea
          rows={3}
          value={cfg.description ?? ""}
          onChange={(e) => onChange({ config: { ...node.config, description: e.target.value } })}
          placeholder="What this output represents"
          style={{ padding: 8, fontSize: 12, lineHeight: 1.5 }}
        />
      </Field>
      <Field label="Materialization">
        <select
          value={cfg.materialize ?? "view"}
          onChange={(e) => onChange({ config: { ...node.config, materialize: e.target.value } })}
          style={{ padding: "7px 8px", fontSize: 12 }}
        >
          <option value="view">View</option>
          <option value="table">Table</option>
          <option value="parquet">Parquet</option>
        </select>
      </Field>
    </>
  );
}

function TrainedModelEditor({ node, onChange }: { node: PipelineNode; onChange: (p: Partial<PipelineNode>) => void }) {
  const cfg = node.config as { model_id?: string; version_id?: string; prediction_column?: string };
  const [models, setModels] = useState<MLModel[]>([]);
  const [versions, setVersions] = useState<MLModelVersion[]>([]);

  useEffect(() => {
    apiFetch<MLModel[]>("/models").then(setModels).catch(() => setModels([]));
  }, []);

  useEffect(() => {
    if (!cfg.model_id) {
      setVersions([]);
      return;
    }
    apiFetch<MLModelVersion[]>(`/models/${cfg.model_id}/versions`).then(setVersions).catch(() => setVersions([]));
  }, [cfg.model_id]);

  return (
    <>
      <Field label="Model">
        <select
          value={cfg.model_id ?? ""}
          onChange={(e) => onChange({ config: { ...node.config, model_id: e.target.value, version_id: "" } })}
          style={{ padding: "7px 8px", fontSize: 12 }}
        >
          <option value="">-- pick a model --</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>{m.name} ({m.task_type})</option>
          ))}
        </select>
      </Field>
      <Field label="Version">
        <select
          value={cfg.version_id ?? ""}
          onChange={(e) => onChange({ config: { ...node.config, version_id: e.target.value } })}
          style={{ padding: "7px 8px", fontSize: 12 }}
        >
          <option value="">latest ready version</option>
          {versions.map((v) => (
            <option key={v.id} value={v.id}>v{v.version} · {v.status}</option>
          ))}
        </select>
      </Field>
      <Field label="Prediction column">
        <input
          value={cfg.prediction_column ?? "prediction"}
          onChange={(e) => onChange({ config: { ...node.config, prediction_column: e.target.value } })}
          className="font-mono"
          style={{ padding: "7px 8px", fontSize: 12 }}
        />
      </Field>
    </>
  );
}
