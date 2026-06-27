"use client";

import type { NodeType } from "@/lib/pipelines";
import { NODE_DESCRIPTIONS, NODE_LABELS } from "@/lib/pipelines";
import { DRAG_MIME } from "./DatasetPalette";

const TRANSFORM_TYPES: NodeType[] = ["join", "union", "filter", "formula", "select", "trained_model", "output"];

export function NodeTypePalette({ onAddType }: { onAddType?: (type: NodeType) => void }) {
  function onDragStart(e: React.DragEvent<HTMLDivElement>, t: NodeType) {
    const payload = JSON.stringify({ kind: "node_type", node_type: t });
    e.dataTransfer.setData(DRAG_MIME, payload);
    e.dataTransfer.setData("text/plain", payload);
    e.dataTransfer.effectAllowed = "copy";
  }
  return (
    <div style={{ display: "grid", gap: 4, marginTop: 4 }}>
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--muted-2)",
          marginTop: 8,
          paddingTop: 8,
          borderTop: "1px solid var(--line-soft)",
        }}
      >
        Transforms
      </div>
      {TRANSFORM_TYPES.map((t) => (
        <div
          key={t}
          draggable
          onDragStart={(e) => onDragStart(e, t)}
          onDoubleClick={() => onAddType?.(t)}
          style={{
            padding: "6px 9px",
            border: "1px solid var(--line)",
            background: "var(--panel)",
            borderRadius: 3,
            cursor: "grab",
            display: "grid",
            gap: 2,
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 600 }}>{NODE_LABELS[t]}</div>
          <div style={{ fontSize: 10.5, color: "var(--muted)", lineHeight: 1.35 }}>
            {NODE_DESCRIPTIONS[t]}
          </div>
          {onAddType ? (
            <button
              type="button"
              className="btn-ghost"
              onClick={(e) => {
                e.stopPropagation();
                onAddType(t);
              }}
              style={{ justifySelf: "start", marginTop: 4, padding: "3px 7px", fontSize: 11 }}
            >
              Add
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}
