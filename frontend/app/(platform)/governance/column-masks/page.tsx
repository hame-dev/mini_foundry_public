"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import {
  ColumnMask,
  createColumnMask,
  deleteColumnMask,
  GovDataset,
  listColumnMasks,
  listGovDatasets,
  MASK_TYPES,
} from "@/lib/governance";
import { ApiError } from "@/lib/api";

export default function GovernanceColumnMasksPage() {
  const [datasets, setDatasets] = useState<GovDataset[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [masks, setMasks] = useState<ColumnMask[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [columnName, setColumnName] = useState("");
  const [subjectType, setSubjectType] = useState("role");
  const [subjectId, setSubjectId] = useState("");
  const [maskType, setMaskType] = useState<string>("hidden");

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

  const loadMasks = useCallback(async (dsId: string) => {
    if (!dsId) return;
    setError(null);
    try {
      setMasks(await listColumnMasks(dsId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load column masks.");
    }
  }, []);

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);

  useEffect(() => {
    if (datasetId) void loadMasks(datasetId);
  }, [datasetId, loadMasks]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!datasetId || !columnName.trim() || !subjectId.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createColumnMask({
        dataset_id: datasetId,
        column_name: columnName.trim(),
        subject_type: subjectType,
        subject_id: subjectId.trim(),
        mask_type: maskType,
      });
      setColumnName("");
      setSubjectId("");
      await loadMasks(datasetId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create column mask.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    setError(null);
    try {
      await deleteColumnMask(id);
      await loadMasks(datasetId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to delete mask.");
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Column masks" type="Governance" status={`${masks.length} masks`} />
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
                <h2 className="font-semibold">Masks on this dataset</h2>
                <p className="text-sm text-[var(--muted)]">A subject sees the masked form of the column.</p>
              </div>
              {masks.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                      <tr>
                        <th className="px-4 py-3">Column</th>
                        <th className="px-4 py-3">Subject</th>
                        <th className="px-4 py-3">Mask</th>
                        <th className="px-4 py-3" />
                      </tr>
                    </thead>
                    <tbody>
                      {masks.map((m) => (
                        <tr key={m.id} className="border-t border-[var(--line-soft)]">
                          <td className="px-4 py-3 font-medium">{m.column_name}</td>
                          <td className="px-4 py-3 text-xs">{m.subject_type}{m.subject_id ? ` · ${m.subject_id.slice(0, 8)}` : ""}</td>
                          <td className="px-4 py-3 font-mono text-xs">{m.mask_type}</td>
                          <td className="px-4 py-3 text-right">
                            <button type="button" className="toolbar-button" onClick={() => void handleDelete(m.id)}>Delete</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="p-4"><EmptyState title="No column masks" detail="All columns are shown in full to all subjects." /></div>
              )}
            </section>

            <aside>
              <form className="app-card space-y-3 p-4" onSubmit={handleCreate}>
                <h2 className="font-semibold">Add column mask</h2>
                <label className="block text-xs font-medium text-[var(--muted)]">
                  Column
                  <input className="input-dark mt-1 w-full" value={columnName} onChange={(e) => setColumnName(e.target.value)} placeholder="e.g. ssn" />
                </label>
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
                  Mask type
                  <select className="input-dark mt-1 w-full" value={maskType} onChange={(e) => setMaskType(e.target.value)}>
                    {MASK_TYPES.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                </label>
                <button type="submit" className="toolbar-button w-full justify-center" disabled={saving || !datasetId || !columnName.trim() || !subjectId.trim()}>
                  {saving ? "Saving" : "Add mask"}
                </button>
              </form>
            </aside>
          </div>
        </>
      ) : null}
    </div>
  );
}
