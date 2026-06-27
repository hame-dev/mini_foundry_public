"use client";

export default function ObjectProperties({
  properties,
  title = "Properties",
}: { properties: Record<string, unknown>; title?: string }) {
  const entries = Object.entries(properties);
  if (entries.length === 0) return null;
  return (
    <section className="app-card p-4">
      <h2 className="text-sm font-semibold mb-2" style={{ color: "var(--text-2)" }}>{title}</h2>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        {entries.map(([k, v]) => (
          <div key={k} className="contents">
            <dt style={{ color: "var(--muted)" }}>{k}</dt>
            <dd className="font-mono" style={{ color: "var(--text)" }}>{v === null || v === undefined ? "—" : String(v)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
