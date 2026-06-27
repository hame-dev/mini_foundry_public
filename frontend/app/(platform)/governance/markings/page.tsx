"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { MarkingBadge } from "@/components/platform/MarkingBadge";
import {
  createMarking,
  grantMarkingEligibility,
  listMarkingEligibility,
  listMarkings,
  Marking,
  MarkingEligibility,
  revokeMarkingEligibility,
} from "@/lib/governance";
import { ApiError } from "@/lib/api";

const principalTypes: MarkingEligibility["principal_type"][] = ["user", "role", "group", "all_users"];

export default function GovernanceMarkingsPage() {
  const [markings, setMarkings] = useState<Marking[]>([]);
  const [eligibility, setEligibility] = useState<MarkingEligibility[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [principalType, setPrincipalType] = useState<MarkingEligibility["principal_type"]>("group");
  const [principalId, setPrincipalId] = useState("");
  const [selectedMarking, setSelectedMarking] = useState("");

  const eligibilityByMarking = useMemo(() => {
    return eligibility.reduce<Record<string, MarkingEligibility[]>>((acc, row) => {
      acc[row.marking_name] = [...(acc[row.marking_name] ?? []), row];
      return acc;
    }, {});
  }, [eligibility]);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const [markingRows, eligibilityRows] = await Promise.all([listMarkings(), listMarkingEligibility()]);
      setMarkings(markingRows);
      setEligibility(eligibilityRows);
      setSelectedMarking((current) => current || markingRows[0]?.name || "");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load markings.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreateMarking(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const marking = await createMarking({ name: name.trim(), description: description.trim() || null });
      setName("");
      setDescription("");
      setSelectedMarking(marking.name);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to create marking.");
    } finally {
      setSaving(false);
    }
  }

  async function handleGrantEligibility(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedMarking) return;
    if (principalType !== "all_users" && !principalId.trim()) {
      setError("Principal ID is required unless the principal type is all_users.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await grantMarkingEligibility({
        principal_type: principalType,
        principal_id: principalType === "all_users" ? null : principalId.trim(),
        marking_name: selectedMarking,
      });
      setPrincipalId("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to grant marking eligibility.");
    } finally {
      setSaving(false);
    }
  }

  async function handleRevoke(row: MarkingEligibility) {
    setSaving(true);
    setError(null);
    try {
      await revokeMarkingEligibility(row.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to revoke marking eligibility.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <ResourceHeader title="Markings" type="Governance" status={`${markings.length} markings`} />
      {loading ? <LoadingState label="Loading markings and eligibility..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="font-semibold">Marking registry</h2>
              <p className="text-sm text-[var(--muted)]">Markings gate resource access before ACL capabilities are applied.</p>
            </div>
            {markings.length ? (
              <div className="divide-y divide-[var(--line-soft)]">
                {markings.map((marking) => {
                  const rows = eligibilityByMarking[marking.name] ?? [];
                  return (
                    <article key={marking.id} className="p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <MarkingBadge name={marking.name} />
                          <p className="mt-2 text-sm text-[var(--muted)]">{marking.description || "No description"}</p>
                        </div>
                        <div className="text-xs text-[var(--muted)]">{rows.length} eligible principals</div>
                      </div>
                      <div className="mt-4 overflow-x-auto">
                        <table className="w-full text-left text-xs">
                          <thead className="text-[var(--muted)]">
                            <tr>
                              <th className="py-2">Principal type</th>
                              <th className="py-2">Principal ID</th>
                              <th className="py-2">Granted</th>
                              <th className="py-2 text-right">Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {rows.map((row) => (
                              <tr key={row.id} className="border-t border-[var(--line-soft)]">
                                <td className="py-2">{row.principal_type}</td>
                                <td className="max-w-[240px] truncate py-2 font-mono">{row.principal_id || "all users"}</td>
                                <td className="py-2 text-[var(--muted)]">{new Date(row.created_at).toLocaleString()}</td>
                                <td className="py-2 text-right">
                                  <button type="button" className="toolbar-button" disabled={saving} onClick={() => void handleRevoke(row)}>
                                    Revoke
                                  </button>
                                </td>
                              </tr>
                            ))}
                            {!rows.length ? (
                              <tr>
                                <td className="py-3 text-[var(--muted)]" colSpan={4}>
                                  No eligibility grants for this marking.
                                </td>
                              </tr>
                            ) : null}
                          </tbody>
                        </table>
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="p-4">
                <EmptyState title="No markings" detail="Create a marking before applying protected access controls to resources." />
              </div>
            )}
          </section>

          <aside className="space-y-4">
            <form className="app-card space-y-3 p-4" onSubmit={handleCreateMarking}>
              <h2 className="font-semibold">Create marking</h2>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Name
                <input className="input-dark mt-1 w-full" value={name} onChange={(event) => setName(event.target.value)} />
              </label>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Description
                <textarea className="input-dark mt-1 min-h-20 w-full" value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
              <button type="submit" className="toolbar-button w-full justify-center" disabled={saving || !name.trim()}>
                {saving ? "Saving" : "Create marking"}
              </button>
            </form>

            <form className="app-card space-y-3 p-4" onSubmit={handleGrantEligibility}>
              <h2 className="font-semibold">Grant eligibility</h2>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Marking
                <select className="input-dark mt-1 w-full" value={selectedMarking} onChange={(event) => setSelectedMarking(event.target.value)}>
                  {markings.map((marking) => (
                    <option key={marking.id} value={marking.name}>
                      {marking.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs font-medium text-[var(--muted)]">
                Principal type
                <select
                  className="input-dark mt-1 w-full"
                  value={principalType}
                  onChange={(event) => setPrincipalType(event.target.value as MarkingEligibility["principal_type"])}
                >
                  {principalTypes.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </label>
              {principalType !== "all_users" ? (
                <label className="block text-xs font-medium text-[var(--muted)]">
                  Principal ID
                  <input
                    className="input-dark mt-1 w-full"
                    placeholder="User or group ID"
                    value={principalId}
                    onChange={(event) => setPrincipalId(event.target.value)}
                  />
                </label>
              ) : null}
              <button type="submit" className="toolbar-button w-full justify-center" disabled={saving || !selectedMarking}>
                {saving ? "Saving" : "Grant eligibility"}
              </button>
            </form>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
