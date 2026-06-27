"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { previewAction, triggerAction, type ActionPreview, type OntologyActionOut } from "@/lib/actions";
import { idempotencyKey } from "@/lib/idempotency";
import type { ObjectSchema, ObjectRow } from "@/lib/ontology";

type Props = {
  action: OntologyActionOut;
  defaultParams?: Record<string, unknown>;
};

export default function ActionTriggerButton({ action, defaultParams }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [properties, setProperties] = useState<any[]>([]);
  const [primaryKey, setPrimaryKey] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, any>>({});
  const [preview, setPreview] = useState<ActionPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const objectType = action.object_type || (defaultParams?.object_type as string);
  const objectId = defaultParams?.object_id as string;
  const isDelete = action.workflow_key.toLowerCase().includes("delete") || action.workflow_key.toLowerCase().includes("remove");

  useEffect(() => {
    if (!isOpen) return;

    setError(null);
    setResult(null);
    setPreview(null);

    // If it's a writeback action, fetch the object schema to generate form fields
    if (objectType) {
      setLoadingSchema(true);
      Promise.all([
        apiFetch<ObjectSchema>(`/ontology/objects/${objectType}`),
        objectId ? apiFetch<ObjectRow>(`/objects/${objectType}/${encodeURIComponent(objectId)}`) : Promise.resolve(null)
      ])
        .then(([schemaData, rowData]) => {
          setProperties(schemaData.object.properties || []);
          setPrimaryKey(schemaData.object.primary_key);
          
          // Initialize form values
          const initialValues: Record<string, any> = {};
          if (rowData) {
            // Prefill with current values for update
            schemaData.object.properties.forEach((p: any) => {
              const name = p.name || p.column;
              initialValues[name] = rowData.properties[name] ?? "";
            });
            // Include primary key
            initialValues[schemaData.object.primary_key] = objectId;
            initialValues["id"] = objectId;
          } else {
            // Prefill defaults if create
            schemaData.object.properties.forEach((p: any) => {
              const name = p.name || p.column;
              initialValues[name] = "";
            });
          }
          setFormValues(initialValues);
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoadingSchema(false));
    } else if (action.input_schema) {
      // Prefill generic input schema fields
      const initialValues: Record<string, any> = {};
      const props = action.input_schema.properties || {};
      Object.keys(props).forEach((key) => {
        initialValues[key] = "";
      });
      setFormValues(initialValues);
    }
  }, [isOpen, objectType, objectId, action.input_schema]);

  const payloadParams = {
    ...(defaultParams || {}),
    ...formValues,
  };
  const schemaProps = action.input_schema?.properties || {};
  const requiredFields = new Set(action.input_schema?.required || []);

  useEffect(() => {
    if (!isOpen || loadingSchema) return;
    let cancelled = false;
    setPreviewLoading(true);
    previewAction(action.name, payloadParams)
      .then((next) => {
        if (!cancelled) setPreview(next);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // formValues is intentionally the trigger; payloadParams is rebuilt from it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, loadingSchema, action.name, formValues]);

  async function submitForm(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);

    try {
      const latestPreview = await previewAction(action.name, payloadParams);
      setPreview(latestPreview);
      if (!latestPreview.allowed) {
        throw new Error(action.permission_explanation || "You do not have permission to run this action.");
      }
      if (!latestPreview.preconditions_ok) {
        throw new Error(latestPreview.missing_preconditions.join("; ") || "Action preconditions failed.");
      }

      const out = await triggerAction(action.name, payloadParams, idempotencyKey("action"));
      if (out.status === "queued") {
        setResult(`queued: ${out.job_id}`);
      } else if (out.status === "pending_approval") {
        setResult(`approval requested: ${out.approval_request_id}`);
      } else {
        setResult(out.status || "succeeded");
      }
      
      const shouldRefresh = out.status === "succeeded";
      setTimeout(() => {
        setIsOpen(false);
        if (shouldRefresh) window.location.reload();
      }, shouldRefresh ? 1000 : 1800);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="inline-block">
      <button
        onClick={() => setIsOpen(true)}
        disabled={!action.enabled || action.can_run === false}
        className="btn-ghost text-sm disabled:opacity-50"
        title={action.can_run === false ? action.permission_explanation || "Permission required" : undefined}
      >
        {action.name}
        {action.approval_required ? <span className="ml-2 badge">approval</span> : null}
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div style={{ background: "var(--panel)", border: "1px solid var(--line)", borderRadius: 8 }} className="shadow-2xl max-w-lg w-full overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            {/* Header */}
            <div style={{ background: "var(--panel-2)", borderBottom: "1px solid var(--line)" }} className="px-6 py-4 flex items-center justify-between">
              <div>
                <h3 style={{ color: "var(--text)" }} className="text-lg font-bold">{action.name}</h3>
                <p style={{ color: "var(--muted)" }} className="text-xs mt-0.5">{action.description || "Run ontology workflow"}</p>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                style={{ color: "var(--muted-2)" }}
                className="hover:opacity-80 transition-opacity text-xl font-medium"
              >
                &times;
              </button>
            </div>

            {/* Content */}
            <form onSubmit={submitForm}>
              <div className="p-6 max-h-[60vh] overflow-y-auto space-y-4">
                {error && (
                  <div className="p-3 bg-red-50 border border-red-100 rounded-lg text-sm text-red-600 font-medium">
                    {error}
                  </div>
                )}
                
                {result && (
                  <div className="p-3 bg-green-50 border border-green-100 rounded-lg text-sm text-green-700 font-medium">
                    Action submitted. {result}
                  </div>
                )}

                {action.can_run === false && (
                  <div className="p-3 bg-amber-50 border border-amber-100 rounded-lg text-sm text-amber-800 font-medium">
                    {action.permission_explanation || "You do not have permission to run this action."}
                  </div>
                )}

                {loadingSchema ? (
                  <div className="py-6 text-center text-sm font-medium" style={{ color: "var(--muted)" }}>
                    Loading action schema...
                  </div>
                ) : isDelete ? (
                  <div className="text-sm font-medium" style={{ color: "var(--text-2)" }}>
                    Are you sure you want to run this action? This will delete the selected record.
                  </div>
                ) : objectType ? (
                  // Writeback creation/update fields
                  <div className="grid grid-cols-1 gap-4">
                    {properties.map((p) => {
                      const name = p.name || p.column;
                      // Skip primary key input if we are updating (since it's not editable)
                      if (objectId && (name === primaryKey || p.column === primaryKey)) return null;
                      return (
                        <div key={name} className="flex flex-col gap-1.5">
                          <label className="text-xs font-semibold" style={{ color: "var(--text-2)" }}>
                            {name}
                          </label>
                          <input
                            type={p.type === "number" || p.type === "integer" ? "number" : "text"}
                            value={formValues[name] ?? ""}
                            onChange={(e) =>
                              setFormValues({
                                ...formValues,
                                [name]: p.type === "number" || p.type === "integer" ? Number(e.target.value) : e.target.value,
                              })
                            }
                            className="input-dark"
                            required={requiredFields.has(name)}
                          />
                        </div>
                      );
                    })}
                  </div>
                ) : action.input_schema ? (
                  // Generic Action parameters
                  <div className="grid grid-cols-1 gap-4">
                    {Object.entries(schemaProps).map(([key, schemaVal]: [string, any]) => (
                      <div key={key} className="flex flex-col gap-1.5">
                        <label className="text-xs font-semibold" style={{ color: "var(--text-2)" }}>
                          {key}
                        </label>
                        {schemaVal.description && (
                          <span className="text-xs" style={{ color: "var(--muted)" }}>{schemaVal.description}</span>
                        )}
                        <input
                          type={schemaVal.type === "number" || schemaVal.type === "integer" ? "number" : "text"}
                          value={formValues[key] ?? ""}
                          onChange={(e) =>
                              setFormValues({
                                ...formValues,
                                [key]: schemaVal.type === "number" || schemaVal.type === "integer" ? Number(e.target.value) : e.target.value,
                              })
                          }
                          className="input-dark"
                          required={requiredFields.has(key)}
                        />
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm font-medium" style={{ color: "var(--text-2)" }}>
                    This action will run with no parameters.
                  </div>
                )}

                <div className="rounded border p-3 space-y-2" style={{ borderColor: "var(--line)", background: "var(--panel-2)" }}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold" style={{ color: "var(--text)" }}>Side-effect preview</span>
                    <span className="text-[11px]" style={{ color: "var(--muted)" }}>
                      {previewLoading ? "Checking..." : preview?.approval_required ? "Approval required" : "Ready"}
                    </span>
                  </div>
                  {preview?.missing_preconditions?.length ? (
                    <ul className="text-xs space-y-1" style={{ color: "var(--danger)" }}>
                      {preview.missing_preconditions.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  ) : null}
                  <div className="grid gap-2">
                    {(preview?.side_effects || []).map((effect, idx) => (
                      <div key={idx} className="text-xs font-mono rounded px-2 py-1" style={{ color: "var(--text-2)", background: "var(--panel)" }}>
                        {String(effect.type || "effect")} · {String(effect.object_type || effect.workflow_key || "target")}
                      </div>
                    ))}
                    {!previewLoading && !preview?.side_effects?.length ? (
                      <div className="text-xs" style={{ color: "var(--muted)" }}>No side effects reported.</div>
                    ) : null}
                  </div>
                </div>
              </div>

              {/* Footer */}
              <div style={{ background: "var(--panel-2)", borderTop: "1px solid var(--line)" }} className="px-6 py-4 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  disabled={busy}
                  className="btn-ghost text-sm disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={busy || loadingSchema || previewLoading || action.can_run === false || preview?.allowed === false || preview?.preconditions_ok === false}
                  className="btn-primary text-sm disabled:opacity-50"
                >
                  {busy ? "Running..." : action.approval_required || preview?.approval_required ? "Request approval" : "Run action"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
