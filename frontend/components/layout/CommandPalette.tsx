"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";

type ExploreResult = {
  id: string;
  kind: "dataset" | "pipeline" | "object" | "saved_query" | "column" | "resource" | "comment";
  name: string;
  subtitle: string | null;
  href: string;
};

const KIND_LABEL: Record<ExploreResult["kind"], string> = {
  dataset: "Dataset",
  pipeline: "Pipeline",
  object: "Object",
  saved_query: "Saved query",
  column: "Column",
  resource: "Resource",
  comment: "Comment",
};

const STATIC_ENTRIES: { name: string; subtitle: string; href: string }[] = [
  { name: "Workspace", subtitle: "Folders and files", href: "/workspace" },
  { name: "Data Catalog", subtitle: "All datasets", href: "/data/catalog" },
  { name: "Pipelines", subtitle: "Visual pipeline builder", href: "/build/pipelines" },
  { name: "Explore", subtitle: "Find any data artifact", href: "/analytics/explore" },
  { name: "Dashboards", subtitle: "All dashboards", href: "/apps/dashboards" },
  { name: "Notebooks", subtitle: "All notebooks", href: "/develop/notebooks" },
  { name: "SQL", subtitle: "Ad-hoc SQL", href: "/analytics/sql" },
  { name: "Ontology", subtitle: "Object types & relationships", href: "/ontology/manager" },
  { name: "AI Provider", subtitle: "Default provider and model", href: "/settings/ai" },
  { name: "Help Guide", subtitle: "How to use the system", href: "/help" },
];

export function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ExploreResult[]>([]);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    params.set("limit", "12");
    apiFetch<{ results: ExploreResult[] }>(`/explore?${params.toString()}`)
      .then((r) => setResults(r.results))
      .catch(() => setResults([]));
  }, [open, query]);

  const staticMatches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return STATIC_ENTRIES;
    return STATIC_ENTRIES.filter(
      (e) => e.name.toLowerCase().includes(q) || e.subtitle.toLowerCase().includes(q),
    );
  }, [query]);

  const allItems = useMemo(
    () => [
      ...staticMatches.map((e) => ({ kind: "static" as const, ...e })),
      ...results.map((r) => ({ ...r, kind: "explore" as const, resultKind: r.kind })),
    ],
    [staticMatches, results],
  );

  function go(idx: number) {
    const item = allItems[idx];
    if (!item) return;
    onClose();
    router.push(item.href);
  }

  if (!open) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          onClose();
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          setActive((a) => Math.min(a + 1, allItems.length - 1));
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          setActive((a) => Math.max(a - 1, 0));
        } else if (e.key === "Enter") {
          e.preventDefault();
          go(active);
        }
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(10,13,18,0.62)",
        backdropFilter: "blur(2px)",
        zIndex: 100,
        display: "grid",
        placeItems: "start center",
        paddingTop: "12vh",
      }}
    >
      <div
        className="app-card"
        style={{
          width: "100%",
          maxWidth: 560,
          padding: 0,
          display: "grid",
          gridTemplateRows: "auto 1fr",
          maxHeight: "70vh",
          overflow: "hidden",
        }}
      >
        <div style={{ padding: 10, borderBottom: "1px solid var(--line-soft)" }}>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            placeholder="Search · jump to…"
            style={{ width: "100%", padding: "8px 10px", fontSize: 13 }}
          />
        </div>
        <div style={{ overflowY: "auto", padding: 4 }}>
          {allItems.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-help">No matches.</div>
            </div>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {allItems.map((it, i) => (
                <li
                  key={`${it.kind}:${i}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => go(i)}
                  style={{
                    padding: "8px 12px",
                    borderRadius: 2,
                    cursor: "pointer",
                    background: active === i ? "var(--accent-soft)" : "transparent",
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                  }}
                >
                  <span
                    className="badge"
                    style={{ minWidth: 56, justifyContent: "center", textAlign: "center" }}
                  >
                    {it.kind === "static" ? "Section" : KIND_LABEL[it.resultKind]}
                  </span>
                  <div style={{ display: "grid", gap: 1, minWidth: 0 }}>
                    <span style={{ fontSize: 12.5, fontWeight: 600 }}>
                      {it.kind === "static" ? it.name : it.name}
                    </span>
                    <span
                      className="font-mono"
                      style={{ fontSize: 10.5, color: "var(--muted)" }}
                    >
                      {it.kind === "static" ? it.subtitle : it.subtitle ?? ""}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
