"use client";
import { useState } from "react";
import type { DashboardFilter } from "@/lib/dashboards";

type Props = {
  filters: DashboardFilter[];
  onChange: (values: Record<string, unknown>) => void;
};

export default function FilterBar({ filters, onChange }: Props) {
  const [values, setValues] = useState<Record<string, unknown>>({});

  if (!filters.length) return null;

  function update(id: string, v: unknown) {
    const next = { ...values, [id]: v };
    setValues(next);
    onChange(next);
  }

  return (
    <div className="app-card flex flex-wrap gap-3 items-end p-3">
      {filters.map((f) => (
        <div key={f.id} className="text-xs">
          <label className="block mb-1" style={{ color: "var(--muted)" }}>{f.label || f.id}</label>
          {f.type === "date_range" && (
            <div className="flex gap-1">
              <input type="date" className="input-dark" onChange={(e) => update(`${f.id}_from`, e.target.value)} />
              <input type="date" className="input-dark" onChange={(e) => update(`${f.id}_to`, e.target.value)} />
            </div>
          )}
          {(f.type === "select" || f.type === "multi_select") && (
            <input type="text" className="input-dark" placeholder="value" onChange={(e) => update(f.id, e.target.value)} />
          )}
          {f.type === "search" && (
            <input type="text" className="input-dark" placeholder="search..." onChange={(e) => update(f.id, e.target.value)} />
          )}
        </div>
      ))}
    </div>
  );
}
