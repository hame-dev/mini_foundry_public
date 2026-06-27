"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import {
  createRowPolicy,
  deleteRowPolicy,
  GovDataset,
  listGovDatasets,
  listRowPolicies,
  RowPolicy,
} from "@/lib/governance";
import { ApiError } from "@/lib/api";

export default function GovernanceRowPoliciesPage() {
  const [datasets, setDatasets] = useState<GovDataset[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [policies, setPolicies] = useState<RowPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // create form
  const [subjectType, setSubjectType] = useState("role");
  const [subjectId, setSubjectId] = useState("");
  const [column, setColumn] = useState("");
  const [op, setOp] = useState<"equals" | "not_equals" | "in">("equals");
  const [value, setValue] = useState("");

  const loadDatasets = useCallback(async () => {
    try {
      const rows = await listGovDatasets();
      setDatasets(rows);
      setDatasetId((cur) => cur || rows[0]?.id || "");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load datasets.");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadPolicies = useCallback(async (dsId: string) => {
    if (!dsId) return;
    setError(null);
    try {
      setPolicies(await listRowPolicies(dsId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load row policies.");
    }
  }, []);

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);

  useEffect(() => {
    if (datasetId) void loadPolicies(datasetId);
  }, [datasetId, loadPolicies]);

  function buildConditionJson(): Record<string, unknown> {
    if (op === "in") {
      return { op: "in", column, values: value.split(",").map((v) => v.trim()).filter(Boolean) };
    }
    return { op, column, value };
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!datasetId || !column.trim() || !subjectId.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createRowPolicy({
        dataset_id: datasetId,
        subject_type: subjectType,
        subject_id: subjectId.trim(),
        condition_json: buildConditionJson(),
      });
      setColumn("");
      setValue("");
      setSubjectId("");
      await loadPolicies(datasetId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create row policy.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    setError(null);
    try {
      await deleteRowPolicy(id);
      await loadPolicies(datasetId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to delete policy.");
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Row policies" type="Governance" status={`${policies.length} policies`} />
      {loading ? <LoadingState label="Loading..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading ? (
        <>
          <div className="app-card flex flex-wrap items-end gap-3 p-4">
            <label className="block text-xs font-medium text-[var(--muted)]">
              Dataset
              <select className="input-dark mt-1 w-64" value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
                {datasets.map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
              </select>
            </label>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <section className="app-card overflow-hidden">
              <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
                <h2 className="font-semibold">Policies on this dataset</h2>
                <p className="text-sm text-[var(--muted)]">A subject sees only rows matching its condition.</p>
              </div>
              {policies.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                      <tr>
                        <th className="px-4 py-3">Subject</th>
                        <th className="px-4 py-3">Condition</th>
                        <th className="px-4 py-3" />
                      </tr>
                    </thead>
                    <tbody>
                      {policies.map((p) => (
                        <tr key={p.id} className="border-t border-[var(--line-soft)]">
                          <td className="px-4 py-3 text-xs">{p.subject_type}{p.subject_id ? ` · ${p.subject_id.slice(0, 8)}` : ""}</td>
                          <td className="px-4 py-3 font-mono text-xs">{p.sql_condition}</td>
                          <td className="px-4 py-3 text-right">
                            <button type="button" className="toolbar-button" onClick={() => void handleDelete(p.id)}>Delete</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="p-4"><EmptyState title="No row policies" detail="All subjects see all rows on this dataset." /></div>
              )}
            </section>

            <aside>
              <form className="app-card space-y-3 p-4" onSubmit={handleCreate}>
                <h2 className="font-semibold">Add row policy</h2>
                <label className="block text-xs font-medium text-[var(--muted)]">
                  Subject type
                  <select className="input-dark mt-1 w-full" value={subjectType} onChange={(e) => setSubjectType(e.target.value)}>
                    <option value="user">user</option>
                    <option value="role">role</option>
                    <option value="group">group</option>
                  </select>
                </label>
                <label className="block text-xs font-medium text-[var(--muted)]">
                  Subject ID
                  <input className="input-dark mt-1 w-full" value={subjectId} onChange={(e) => setSubjectId(e.target.value)} placeholder="user/role/group UUID" />
                </label>
                <label className="block text-xs font-medium text-[var(--muted)]">
                  Column
                  <input className="input-dark mt-1 w-full" value={column} onChange={(e) => setColumn(e.target.value)} placeholder="e.g. region" />
                </label>
                <label className="block text-xs font-medium text-[var(--muted)]">
                  Operator
                  <select className="input-dark mt-1 w-full" value={op} onChange={(e) => setOp(e.target.value as typeof op)}>
                    <option value="equals">equals</option>
                    <option value="not_equals">not equals</option>
                    <option value="in">in (comma-separated)</option>
                  </select>
                </label>
                <label className="block text-xs font-medium text-[var(--muted)]">
                  Value{op === "in" ? "s" : ""}
                  <input className="input-dark mt-1 w-full" value={value} onChange={(e) => setValue(e.target.value)} placeholder={op === "in" ? "EMEA, APAC" : "EMEA"} />
                </label>
                <button type="submit" className="toolbar-button w-full justify-center" disabled={saving || !datasetId || !column.trim() || !subjectId.trim()}>
                  {saving ? "Saving" : "Add policy"}
                </button>
              </form>
            </aside>
          </div>
        </>
      ) : null}
    </div>
  );
}
