"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Dataset } from "@/lib/types";

const DRAG_MIME = "application/x-mf-dataset";

type Props = {
  datasets?: Dataset[];
  selectedIds?: Set<string>;
  onToggleDataset?: (id: string) => void;
  onAddSelected?: () => void;
};

export function DatasetPalette({ datasets: supplied, selectedIds, onToggleDataset, onAddSelected }: Props = {}) {
  const [loaded, setLoaded] = useState<Dataset[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const datasets = supplied ?? loaded;

  useEffect(() => {
    if (supplied) return;
    apiFetch<Dataset[]>("/catalog/datasets")
      .then(setLoaded)
      .catch((e) => setError(e.message));
  }, [supplied]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return datasets;
    return datasets.filter(
      (d) =>
        d.name.toLowerCase().includes(q) ||
        `${d.schema_name}.${d.table_name}`.toLowerCase().includes(q),
    );
  }, [datasets, query]);

  function handleDragStart(e: React.DragEvent<HTMLDivElement>, d: Dataset) {
    const payload = JSON.stringify({ kind: "dataset", dataset_id: d.id, name: d.name });
    e.dataTransfer.setData(DRAG_MIME, payload);
    e.dataTransfer.setData("text/plain", payload);
    e.dataTransfer.effectAllowed = "copy";
  }

  return (
    <aside
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: 12,
        borderRight: "1px solid var(--line)",
        background: "var(--bg-2)",
        minHeight: 0,
        flex: 1,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--muted-2)",
        }}
      >
        Datasets
      </div>
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter…"
        style={{ width: "100%", padding: "6px 10px", fontSize: 12 }}
      />
      <div
        style={{
          fontSize: 11,
          color: "var(--muted-2)",
          lineHeight: 1.4,
          paddingBottom: 4,
          borderBottom: "1px solid var(--line-soft)",
        }}
      >
        Select datasets and add them as sources, or drag one dataset onto the graph.
      </div>

      {onAddSelected ? (
        <button
          type="button"
          className="btn-primary"
          onClick={onAddSelected}
          disabled={!selectedIds?.size}
          style={{ justifyContent: "center" }}
        >
          Add selected {selectedIds?.size ? `(${selectedIds.size})` : ""}
        </button>
      ) : null}

      <div style={{ overflowY: "auto", display: "grid", gap: 4, minHeight: 0 }}>
        {error ? (
          <div style={{ color: "var(--danger)", fontSize: 11 }}>{error}</div>
        ) : filtered.length === 0 ? (
          <div style={{ color: "var(--muted-2)", fontSize: 11 }}>No datasets.</div>
        ) : (
          filtered.map((d) => (
            <div
              key={d.id}
              draggable
              onDragStart={(e) => handleDragStart(e, d)}
              style={{
                display: "grid",
                gridTemplateColumns: onToggleDataset ? "auto 1fr" : "1fr",
                gap: 8,
                alignItems: "start",
                padding: "7px 9px",
                border: "1px solid var(--line)",
                background: selectedIds?.has(d.id) ? "var(--accent-soft)" : "var(--panel)",
                borderRadius: 3,
                cursor: "grab",
              }}
            >
              {onToggleDataset ? (
                <input
                  type="checkbox"
                  checked={Boolean(selectedIds?.has(d.id))}
                  onChange={() => onToggleDataset(d.id)}
                  onClick={(e) => e.stopPropagation()}
                  style={{ marginTop: 2 }}
                />
              ) : null}
              <div style={{ display: "grid", gap: 2, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>{d.name}</div>
                <div
                  className="font-mono"
                  style={{ fontSize: 10.5, color: "var(--muted)" }}
                >
                  {d.schema_name}.{d.table_name}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}

export { DRAG_MIME };
