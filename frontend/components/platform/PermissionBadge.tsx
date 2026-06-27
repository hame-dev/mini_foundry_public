export function PermissionBadge({ label = "Inherited access" }: { label?: string }) {
  return <span className="topbar-pill">Access · {label}</span>;
}
