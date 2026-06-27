/**
 * Shared status vocabulary and tone mapping (frontend README §23).
 * Keeping the status → tone map in one place keeps color usage consistent across
 * StatusPill, badges, tables, and headers in both themes.
 */

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger" | "branch" | "masked";

export type StatusName =
  | "Draft"
  | "Validating"
  | "Ready"
  | "Running"
  | "Succeeded"
  | "Failed"
  | "Canceled"
  | "Paused"
  | "Stale"
  | "Out of date"
  | "Permission denied"
  | "Needs approval"
  | "Approved"
  | "Rejected"
  | "Merged"
  | "Deprecated"
  | "Certified"
  | "Experimental";

const STATUS_TONES: Record<string, StatusTone> = {
  draft: "neutral",
  validating: "info",
  ready: "info",
  running: "info",
  queued: "info",
  syncing: "info",
  active: "success",
  succeeded: "success",
  success: "success",
  healthy: "success",
  ok: "success",
  approved: "success",
  certified: "success",
  merged: "branch",
  failed: "danger",
  error: "danger",
  rejected: "danger",
  "permission denied": "danger",
  denied: "danger",
  canceled: "neutral",
  cancelled: "neutral",
  paused: "warning",
  stale: "warning",
  "out of date": "warning",
  degraded: "warning",
  "needs approval": "warning",
  pending: "warning",
  deprecated: "neutral",
  experimental: "warning",
};

/** Resolve a free-form status string to a consistent tone. */
export function statusTone(status: string | null | undefined): StatusTone {
  if (!status) return "neutral";
  return STATUS_TONES[status.trim().toLowerCase()] ?? "neutral";
}

/** Tailwind-free CSS class for the badge variant matching a tone. */
export function toneBadgeClass(tone: StatusTone): string {
  switch (tone) {
    case "success":
      return "badge-success";
    case "warning":
      return "badge-warning";
    case "danger":
      return "badge-danger";
    case "info":
      return "badge-info";
    case "branch":
      return "badge-branch";
    case "masked":
      return "badge-masked";
    default:
      return "";
  }
}
