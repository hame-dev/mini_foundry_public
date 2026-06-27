export function LoadingState({ label = "Loading..." }: { label?: string }) {
  return <div className="app-card p-4 text-sm text-[var(--muted)]">{label}</div>;
}

export function EmptyState({ title = "Nothing here yet", detail }: { title?: string; detail?: string }) {
  return (
    <div className="app-card p-4">
      <h2 className="font-semibold">{title}</h2>
      {detail && <p className="text-sm text-[var(--muted)]">{detail}</p>}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return <div className="app-card p-4 text-sm text-red-300">{message}</div>;
}

export function PermissionDenied({ message = "You do not have permission to view this resource." }: { message?: string }) {
  return (
    <div className="app-card p-4">
      <h2 className="font-semibold">Permission denied</h2>
      <p className="text-sm text-[var(--muted)]">{message}</p>
    </div>
  );
}
