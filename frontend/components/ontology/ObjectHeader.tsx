"use client";

export default function ObjectHeader({
  typeName, id, displayName,
}: { typeName: string; id: string; displayName: string | null }) {
  return (
    <header>
      <div style={{ color: "var(--muted-2)", fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase" }}>{typeName}</div>
      <h1 style={{ color: "var(--text)" }} className="text-2xl font-semibold">{displayName || id}</h1>
      <div style={{ color: "var(--muted)", fontSize: 11 }} className="font-mono mt-1">id: {id}</div>
    </header>
  );
}
