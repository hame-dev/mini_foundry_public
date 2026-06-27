"use client";

import { Handle, Position } from "@xyflow/react";
import type { ReactNode } from "react";
import type { NodeType } from "@/lib/pipelines";
import { NODE_LABELS } from "@/lib/pipelines";

type Variant = "neutral" | "source" | "join" | "output";

const VARIANT_STYLES: Record<Variant, { border: string; bg: string; accent: string }> = {
  neutral: {
    border: "var(--line)",
    bg: "var(--panel)",
    accent: "var(--muted-2)",
  },
  source: {
    border: "var(--accent-line)",
    bg: "var(--panel)",
    accent: "var(--accent)",
  },
  join: {
    border: "rgba(62, 198, 192, 0.4)",
    bg: "var(--panel)",
    accent: "var(--teal)",
  },
  output: {
    border: "rgba(76, 212, 150, 0.45)",
    bg: "var(--panel)",
    accent: "var(--success)",
  },
};

export function NodeCard({
  title,
  subtitle,
  nodeType,
  variant = "neutral",
  selected,
  badge,
  body,
  inputs = [],
  outputs = ["out"],
  width = 220,
}: {
  title: string;
  subtitle?: string | null;
  nodeType: NodeType;
  variant?: Variant;
  selected?: boolean;
  badge?: ReactNode;
  body?: ReactNode;
  inputs?: { id: string; label?: string }[];
  outputs?: string[];
  width?: number;
}) {
  const v = VARIANT_STYLES[variant];
  return (
    <div
      style={{
        width,
        background: v.bg,
        border: `1px solid ${selected ? "var(--accent)" : v.border}`,
        borderRadius: 3,
        boxShadow: selected
          ? "0 0 0 2px var(--accent-soft), 0 12px 28px rgba(0,0,0,0.32)"
          : "0 6px 16px rgba(0,0,0,0.22)",
        fontFamily: "var(--font-sans)",
        color: "var(--text)",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "7px 9px",
          borderBottom: "1px solid var(--line-soft)",
          background:
            "linear-gradient(180deg, rgba(255,255,255,0.02), rgba(0,0,0,0.08))",
        }}
      >
        <span
          aria-hidden
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: 6,
            background: v.accent,
          }}
        />
        <span
          style={{
            fontSize: 9.5,
            fontWeight: 700,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--muted-2)",
          }}
        >
          {NODE_LABELS[nodeType]}
        </span>
        {badge ? <span style={{ marginLeft: "auto" }}>{badge}</span> : null}
      </div>

      {/* Body */}
      <div style={{ padding: "8px 9px", display: "grid", gap: 4 }}>
        <div style={{ fontSize: 12.5, fontWeight: 650, color: "var(--text)", lineHeight: 1.25 }}>
          {title}
        </div>
        {subtitle ? (
          <div
            className="font-mono"
            style={{ fontSize: 10.5, color: "var(--muted)", lineHeight: 1.25 }}
          >
            {subtitle}
          </div>
        ) : null}
        {body}
      </div>

      {/* Input handles */}
      {inputs.map((h, i) => {
        const top = inputs.length === 1 ? "50%" : `${((i + 1) * 100) / (inputs.length + 1)}%`;
        return (
          <Handle
            key={h.id}
            id={h.id}
            type="target"
            position={Position.Left}
            style={{
              top,
              width: 9,
              height: 9,
              background: "var(--bg)",
              border: "1px solid var(--line-strong)",
              borderRadius: 0,
            }}
          >
            {h.label ? (
              <span
                style={{
                  position: "absolute",
                  right: 14,
                  top: -7,
                  fontSize: 9,
                  fontWeight: 700,
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  color: "var(--muted-2)",
                  pointerEvents: "none",
                  background: v.bg,
                  padding: "0 4px",
                }}
              >
                {h.label}
              </span>
            ) : null}
          </Handle>
        );
      })}

      {/* Output handles */}
      {outputs.map((id, i) => {
        const top = outputs.length === 1 ? "50%" : `${((i + 1) * 100) / (outputs.length + 1)}%`;
        return (
          <Handle
            key={id}
            id={id}
            type="source"
            position={Position.Right}
            style={{
              top,
              width: 9,
              height: 9,
              background: v.accent,
              border: "1px solid var(--bg)",
              borderRadius: 0,
            }}
          />
        );
      })}
    </div>
  );
}
