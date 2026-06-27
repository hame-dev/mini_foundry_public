export function MarkingBadge({ name = "Unmarked" }: { name?: string }) {
  return <span className="topbar-pill">Marking · {name}</span>;
}
