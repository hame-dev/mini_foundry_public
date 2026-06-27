"use client";

type Props = {
  title?: string | null;
  rows: Record<string, unknown>[] | undefined;
  config: { value_column?: string; format?: "currency" | "number" | "percent"; label?: string };
};

function formatValue(v: unknown, fmt?: string): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  if (fmt === "currency") return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  if (fmt === "percent") return `${(n * 100).toFixed(1)}%`;
  return n.toLocaleString();
}

export default function MetricCard({ title, rows, config }: Props) {
  const col = config.value_column || "value";
  const value = rows && rows.length > 0 ? rows[0][col] : null;
  return (
    <div className="h-full flex flex-col justify-center p-4">
      <div className="text-xs uppercase tracking-wide text-gray-500">{config.label || title || col}</div>
      <div className="text-3xl font-semibold mt-1">{formatValue(value, config.format)}</div>
    </div>
  );
}
