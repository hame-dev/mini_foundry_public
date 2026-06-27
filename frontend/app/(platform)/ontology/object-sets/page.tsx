"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { OntologyObjectOut } from "@/lib/ontology";
import {
  FILTER_OPERATORS,
  type FilterOperator,
  type FilterPredicate,
  type ObjectSet,
  type ObjectSetResult,
  createObjectSet,
  deleteObjectSet,
  listObjectSets,
  queryObjectSet,
  queryObjects,
} from "@/lib/objectSets";

const NULLARY_OPS: FilterOperator[] = ["is_null", "not_null"];

export default function ObjectSetsPage() {
  const [types, setTypes] = useState<OntologyObjectOut[]>([]);
  const [objectType, setObjectType] = useState<string>("");
  const [predicates, setPredicates] = useState<FilterPredicate[]>([]);
  const [sets, setSets] = useState<ObjectSet[]>([]);
  const [result, setResult] = useState<ObjectSetResult | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const currentType = useMemo(() => types.find((t) => t.type_name === objectType), [types, objectType]);
  const columns = useMemo(() => {
    if (!currentType) return [];
    const cols = (currentType.properties || []).map((p) => p.column);
    if (!cols.includes(currentType.primary_key)) cols.unshift(currentType.primary_key);
    return cols;
  }, [currentType]);

  useEffect(() => {
    apiFetch<OntologyObjectOut[]>("/ontology/objects")
      .then((rows) => {
        setTypes(rows);
        if (rows.length > 0) setObjectType(rows[0].type_name);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!objectType) return;
    setResult(null);
    setPredicates([]);
    listObjectSets(objectType).then(setSets).catch(() => setSets([]));
  }, [objectType]);

  function addPredicate() {
    if (columns.length === 0) return;
    setPredicates((p) => [...p, { column: columns[0], op: "eq", value: "" }]);
  }
  function updatePredicate(i: number, patch: Partial<FilterPredicate>) {
    setPredicates((p) => p.map((pred, idx) => (idx === i ? { ...pred, ...patch } : pred)));
  }
  function removePredicate(i: number) {
    setPredicates((p) => p.filter((_, idx) => idx !== i));
  }

  function normalize(preds: FilterPredicate[]): FilterPredicate[] {
    return preds.map((p) => (NULLARY_OPS.includes(p.op) ? { column: p.column, op: p.op } : p));
  }

  async function runPreview() {
    setError(null);
    setBusy(true);
    try {
      const res = await queryObjects(objectType, normalize(predicates), { limit: 100 });
      setResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!name.trim()) {
      setError("name is required");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await createObjectSet({ name: name.trim(), object_type: objectType, filters: normalize(predicates) });
      setName("");
      const refreshed = await listObjectSets(objectType);
      setSets(refreshed);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runSaved(id: string) {
    setError(null);
    setBusy(true);
    try {
      setResult(await queryObjectSet(id, { limit: 100 }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function removeSaved(id: string) {
    await deleteObjectSet(id).catch(() => {});
    setSets((s) => s.filter((x) => x.id !== id));
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Object Sets</h1>
        <select className="input-dark" value={objectType} onChange={(e) => setObjectType(e.target.value)}>
          {types.map((t) => (
            <option key={t.id} value={t.type_name}>{t.type_name}</option>
          ))}
        </select>
      </div>

      {error && <div className="text-red-600 text-sm">{error}</div>}

      <section className="app-card p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold" style={{ color: "var(--text-2)" }}>Filters</h2>
          <button className="btn-ghost text-xs" onClick={addPredicate} disabled={columns.length === 0}>+ Add filter</button>
        </div>
        {predicates.length === 0 && <p className="text-sm" style={{ color: "var(--muted)" }}>No filters — all objects of this type.</p>}
        {predicates.map((pred, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <select className="input-dark text-xs" value={pred.column} onChange={(e) => updatePredicate(i, { column: e.target.value })}>
              {columns.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <select className="input-dark text-xs" value={pred.op} onChange={(e) => updatePredicate(i, { op: e.target.value as FilterOperator })}>
              {FILTER_OPERATORS.map((op) => <option key={op} value={op}>{op}</option>)}
            </select>
            {!NULLARY_OPS.includes(pred.op) && (
              <input
                className="input-dark text-xs"
                placeholder={pred.op === "in" ? "comma,separated" : "value"}
                value={pred.op === "in" && Array.isArray(pred.value) ? pred.value.join(",") : String(pred.value ?? "")}
                onChange={(e) =>
                  updatePredicate(i, { value: pred.op === "in" ? e.target.value.split(",").map((v) => v.trim()).filter(Boolean) : e.target.value })
                }
              />
            )}
            <button className="btn-ghost text-xs" onClick={() => removePredicate(i)}>✕</button>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2 pt-2">
          <button className="btn-primary text-xs" onClick={runPreview} disabled={busy || !objectType}>Run preview</button>
          <input className="input-dark text-xs w-44" placeholder="Save as…" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn-ghost text-xs" onClick={save} disabled={busy || !objectType}>Save set</button>
        </div>
      </section>

      {sets.length > 0 && (
        <section className="app-card p-4 space-y-2">
          <h2 className="text-sm font-semibold" style={{ color: "var(--text-2)" }}>Saved sets</h2>
          {sets.map((s) => (
            <div key={s.id} className="flex items-center justify-between text-sm">
              <span>{s.name} <span style={{ color: "var(--muted)" }}>({s.filters.length} filters)</span></span>
              <span className="flex gap-2">
                <button className="btn-ghost text-xs" onClick={() => runSaved(s.id)}>Run</button>
                <button className="btn-ghost text-xs" onClick={() => removeSaved(s.id)}>Delete</button>
              </span>
            </div>
          ))}
        </section>
      )}

      {result && (
        <section className="app-card p-4">
          <h2 className="text-sm font-semibold mb-2" style={{ color: "var(--text-2)" }}>
            Results — {result.row_count} object(s)
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ color: "var(--muted)" }}>
                  {result.columns.map((c) => <th key={c} className="text-left px-2 py-1">{c}</th>)}
                </tr>
              </thead>
              <tbody>
                {result.objects.map((o, idx) => {
                  const merged = { ...o.properties, ...o.functions };
                  return (
                    <tr key={idx} className="font-mono">
                      {result.columns.map((c) => (
                        <td key={c} className="px-2 py-1">{merged[c] === null || merged[c] === undefined ? "—" : String(merged[c])}</td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
