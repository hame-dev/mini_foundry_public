"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { OntologyObjectOut } from "@/lib/ontology";
import {
  type OntologyFunction,
  createFunction,
  deleteFunction,
  listFunctions,
} from "@/lib/objectSets";

export default function OntologyFunctionsPage() {
  const [types, setTypes] = useState<OntologyObjectOut[]>([]);
  const [objectType, setObjectType] = useState<string>("");
  const [functions, setFunctions] = useState<OntologyFunction[]>([]);
  const [name, setName] = useState("");
  const [expression, setExpression] = useState("");
  const [returnType, setReturnType] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const currentType = useMemo(() => types.find((t) => t.type_name === objectType), [types, objectType]);

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
    listFunctions(objectType).then(setFunctions).catch(() => setFunctions([]));
  }, [objectType]);

  async function create() {
    setError(null);
    setBusy(true);
    try {
      await createFunction(objectType, {
        name: name.trim(),
        expression: expression.trim(),
        return_type: returnType.trim() || null,
      });
      setName("");
      setExpression("");
      setReturnType("");
      setFunctions(await listFunctions(objectType));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    await deleteFunction(id).catch(() => {});
    setFunctions((f) => f.filter((x) => x.id !== id));
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Functions on Objects</h1>
        <select className="input-dark" value={objectType} onChange={(e) => setObjectType(e.target.value)}>
          {types.map((t) => (
            <option key={t.id} value={t.type_name}>{t.type_name}</option>
          ))}
        </select>
      </div>

      <p className="text-sm" style={{ color: "var(--muted)" }}>
        Computed properties are read-only scalar expressions over this object type&apos;s own columns
        (e.g. <code>quantity * unit_price</code>). They are validated against an allowlist and
        evaluated through the governed query layer; a function over a masked column is redacted.
      </p>

      {error && <div className="text-red-600 text-sm">{error}</div>}

      <section className="app-card p-4 space-y-3">
        <h2 className="text-sm font-semibold" style={{ color: "var(--text-2)" }}>New function</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">
            Name
            <input className="input-dark mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} placeholder="total" />
          </label>
          <label className="text-sm">
            Return type (optional)
            <input className="input-dark mt-1 w-full" value={returnType} onChange={(e) => setReturnType(e.target.value)} placeholder="numeric" />
          </label>
        </div>
        <label className="text-sm block">
          Expression
          <input className="input-dark mt-1 w-full font-mono text-xs" value={expression} onChange={(e) => setExpression(e.target.value)} placeholder="quantity * unit_price" />
        </label>
        {currentType && (
          <p className="text-xs" style={{ color: "var(--muted)" }}>
            Columns: {(currentType.properties || []).map((p) => p.column).join(", ") || "—"}
          </p>
        )}
        <button className="btn-primary text-xs" onClick={create} disabled={busy || !objectType || !name.trim() || !expression.trim()}>
          Create function
        </button>
      </section>

      <section className="app-card p-4 space-y-2">
        <h2 className="text-sm font-semibold" style={{ color: "var(--text-2)" }}>Defined functions</h2>
        {functions.length === 0 && <p className="text-sm" style={{ color: "var(--muted)" }}>None yet.</p>}
        {functions.map((f) => (
          <div key={f.id} className="flex items-center justify-between text-sm">
            <span>
              <span className="font-medium">{f.name}</span>{" "}
              <code className="font-mono text-xs" style={{ color: "var(--muted)" }}>{f.expression}</code>
              {f.return_type ? <span style={{ color: "var(--muted)" }}> : {f.return_type}</span> : null}
            </span>
            <button className="btn-ghost text-xs" onClick={() => remove(f.id)}>Delete</button>
          </div>
        ))}
      </section>
    </div>
  );
}
