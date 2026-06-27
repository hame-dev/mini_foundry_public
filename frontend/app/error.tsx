"use client";

export default function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  return (
    <main style={{ padding: 24, display: "grid", gap: 12 }}>
      <h1 style={{ fontSize: 20, fontWeight: 650 }}>Something went wrong</h1>
      <p style={{ color: "var(--muted)" }}>The page failed to render. The error has been logged.</p>
      <button className="btn-primary px-4 py-2" onClick={reset} type="button">
        Retry
      </button>
    </main>
  );
}
