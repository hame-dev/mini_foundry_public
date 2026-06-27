"use client";

import { useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { EmptyState, ErrorState, LoadingState } from "@/components/platform/States";
import { Capability, CapabilityGrant, listCapabilities, listCapabilityGrants } from "@/lib/governance";
import { ApiError } from "@/lib/api";

export default function GovernanceCapabilitiesPage() {
  const [caps, setCaps] = useState<Capability[]>([]);
  const [grants, setGrants] = useState<CapabilityGrant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [c, g] = await Promise.all([listCapabilities(), listCapabilityGrants()]);
      setCaps(c);
      setGrants(g);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load capabilities.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-5">
      <ResourceHeader title="Capabilities" type="Governance" status={`${caps.length} capabilities`} />
      {loading ? <LoadingState label="Loading capabilities..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && !error ? (
        <div className="grid gap-4 xl:grid-cols-[380px_minmax(0,1fr)]">
          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="font-semibold">Canonical capabilities</h2>
              <p className="text-sm text-[var(--muted)]">The fixed vocabulary granted through resource ACLs.</p>
            </div>
            <ul className="divide-y divide-[var(--line-soft)]">
              {caps.map((c) => (
                <li key={c.name} className="p-4">
                  <div className="font-mono text-sm">{c.name}</div>
                  <div className="text-xs text-[var(--muted)]">{c.description}</div>
                </li>
              ))}
            </ul>
          </section>

          <section className="app-card overflow-hidden">
            <div className="border-b border-[var(--line)] bg-[var(--panel-2)] p-4">
              <h2 className="font-semibold">Grants</h2>
              <p className="text-sm text-[var(--muted)]">Who has which capabilities on which resources.</p>
            </div>
            {grants.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-[var(--panel-2)] text-xs uppercase text-[var(--muted)]">
                    <tr>
                      <th className="px-4 py-3">Resource</th>
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3">Subject</th>
                      <th className="px-4 py-3">Capabilities</th>
                    </tr>
                  </thead>
                  <tbody>
                    {grants.map((g, i) => (
                      <tr key={`${g.resource_id}-${i}`} className="border-t border-[var(--line-soft)]">
                        <td className="px-4 py-3 font-medium">{g.resource_name}</td>
                        <td className="px-4 py-3 text-[var(--muted)]">{g.resource_type}</td>
                        <td className="px-4 py-3 text-xs">
                          {g.subject_type}
                          {g.subject_id ? ` · ${g.subject_id.slice(0, 8)}` : ""}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs">{g.capabilities.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-4">
                <EmptyState title="No grants" detail="Resource ACL grants will appear here." />
              </div>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}
