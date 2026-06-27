"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ResourceHeader } from "@/components/platform/ResourceHeader";
import { ErrorState, LoadingState } from "@/components/platform/States";
import { PoliciesSummary, policiesSummary } from "@/lib/governance";
import { ApiError } from "@/lib/api";

const LINKS = [
  { href: "/governance/row-policies", title: "Row policies", desc: "Row-level filters per dataset and subject.", key: "row_policy_count" as const },
  { href: "/governance/column-masks", title: "Column masks", desc: "Hide or redact sensitive columns.", key: "column_mask_count" as const },
  { href: "/governance/capabilities", title: "Capability grants", desc: "Resource ACL capability assignments.", key: "acl_grant_count" as const },
];

export default function GovernancePoliciesPage() {
  const [summary, setSummary] = useState<PoliciesSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await policiesSummary());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to load policy summary.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-5">
      <ResourceHeader title="Policies" type="Governance" subtitle="Access-control policy overview" />
      {loading ? <LoadingState label="Loading policy summary..." /> : null}
      {error ? <ErrorState message={error} /> : null}

      {!loading && !error ? (
        <section className="grid gap-3 md:grid-cols-3">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="app-card block p-4 transition hover:bg-[var(--panel-2)]">
              <p className="text-xs uppercase tracking-wide text-[var(--muted)]">{l.title}</p>
              <p className="mt-2 text-3xl font-semibold">{summary ? summary[l.key] : "—"}</p>
              <p className="mt-2 text-sm text-[var(--muted)]">{l.desc}</p>
            </Link>
          ))}
        </section>
      ) : null}
    </div>
  );
}
