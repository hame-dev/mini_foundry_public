import type { ReactNode } from "react";
import { Breadcrumbs, type Crumb } from "@/components/foundry/feedback";
import { Badge, StatusPill } from "@/components/foundry/controls";
import { statusTone } from "@/lib/status";

/**
 * Canonical resource header (frontend README §9). Backward compatible with the
 * earlier minimal signature ({ title, type, status, actions }); the richer props
 * (breadcrumb, branch/version, markings, owner, lastUpdated, meta) are optional.
 */
export function ResourceHeader({
  title,
  type,
  status = "Ready",
  breadcrumb,
  branch,
  version,
  markings,
  permissions,
  owner,
  lastUpdated,
  subtitle,
  meta,
  actions,
}: {
  title: string;
  type: string;
  status?: string;
  breadcrumb?: Crumb[];
  branch?: string;
  version?: string;
  markings?: string[];
  permissions?: string[];
  owner?: string;
  lastUpdated?: string;
  subtitle?: string;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  const chips: ReactNode[] = [];
  if (branch) chips.push(<span key="branch" className="resource-meta-chip"><Badge tone="branch">{branch}</Badge></span>);
  if (version) chips.push(<span key="version" className="resource-meta-chip">Version <strong>{version}</strong></span>);
  if (owner) chips.push(<span key="owner" className="resource-meta-chip">Owner <strong>{owner}</strong></span>);
  if (lastUpdated) chips.push(<span key="updated" className="resource-meta-chip">Updated <strong>{lastUpdated}</strong></span>);
  (permissions ?? []).forEach((p, i) => chips.push(<span key={`perm-${i}`} className="resource-meta-chip"><Badge>{p}</Badge></span>));
  (markings ?? []).forEach((m, i) => chips.push(<span key={`mark-${i}`} className="resource-meta-chip"><Badge tone="masked">{m}</Badge></span>));

  return (
    <section className="app-card" style={{ padding: 16, marginBottom: 12 }}>
      {breadcrumb && breadcrumb.length ? (
        <div style={{ marginBottom: 8 }}>
          <Breadcrumbs items={breadcrumb} />
        </div>
      ) : null}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div className="topbar-kicker">{type}</div>
          <h1 style={{ fontSize: 24, margin: "2px 0 0" }}>{title}</h1>
          {subtitle ? <p className="foundry-resource-subtitle">{subtitle}</p> : null}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end", flex: "none" }}>
          <StatusPill status={status} tone={statusTone(status)} />
          {actions}
        </div>
      </div>
      {chips.length || meta ? (
        <div className="foundry-resource-meta">
          {meta}
          {chips}
        </div>
      ) : null}
    </section>
  );
}
