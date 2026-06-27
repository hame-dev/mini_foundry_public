"use client";
import type { DashboardComponent } from "@/lib/dashboards";

type Props = {
  component: DashboardComponent;
  onChange: (next: DashboardComponent) => void;
  onDelete: () => void;
};

export default function PropertiesPanel({ component, onChange, onDelete }: Props) {
  function setTitle(v: string) {
    onChange({ ...component, title: v });
  }
  function setConfig(key: string, v: unknown) {
    onChange({ ...component, config: { ...component.config, [key]: v } });
  }

  const cfg = component.config as Record<string, unknown>;

  return (
    <div className="space-y-3 no-drag">
      <h3 className="text-xs uppercase tracking-wide text-gray-500">Properties</h3>
      <div>
        <label className="block text-xs mb-1">Title</label>
        <input
          className="w-full border rounded px-2 py-1 text-sm"
          value={component.title || ""}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>

      {component.component_type === "metric_card" && (
        <>
          <TextInput label="value_column" value={String(cfg.value_column || "")} onChange={(v) => setConfig("value_column", v)} />
          <SelectInput label="format" value={String(cfg.format || "number")} onChange={(v) => setConfig("format", v)}
            options={["number", "currency", "percent"]} />
          <TextInput label="label (optional)" value={String(cfg.label || "")} onChange={(v) => setConfig("label", v)} />
        </>
      )}

      {(component.component_type === "line_chart" || component.component_type === "bar_chart") && (
        <>
          <TextInput label="x column" value={String(cfg.x || "")} onChange={(v) => setConfig("x", v)} />
          <TextInput label="y column(s) (comma-separated)" value={Array.isArray(cfg.y) ? cfg.y.join(",") : String(cfg.y || "")}
            onChange={(v) => setConfig("y", v.includes(",") ? v.split(",").map((s) => s.trim()) : v)} />
          {component.component_type === "bar_chart" && (
            <CheckInput label="stacked" value={Boolean(cfg.stacked)} onChange={(v) => setConfig("stacked", v)} />
          )}
        </>
      )}

      {component.component_type === "pie_chart" && (
        <>
          <TextInput label="label column" value={String(cfg.label || "")} onChange={(v) => setConfig("label", v)} />
          <TextInput label="value column" value={String(cfg.value || "")} onChange={(v) => setConfig("value", v)} />
        </>
      )}

      {component.component_type === "table" && (
        <TextInput label="columns (comma-separated, blank = all)"
          value={Array.isArray(cfg.columns) ? cfg.columns.join(",") : ""}
          onChange={(v) => setConfig("columns", v ? v.split(",").map((s) => s.trim()) : undefined)} />
      )}

      {component.component_type === "markdown" && (
        <div>
          <label className="block text-xs mb-1">text</label>
          <textarea
            className="w-full border rounded px-2 py-1 text-xs font-mono h-32"
            value={String(cfg.text || "")}
            onChange={(e) => setConfig("text", e.target.value)}
          />
        </div>
      )}

      <button
        onClick={onDelete}
        className="w-full text-sm border border-red-200 text-red-600 rounded py-1 hover:bg-red-50"
      >
        Delete component
      </button>
    </div>
  );
}

function TextInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="block text-xs mb-1">{label}</label>
      <input className="w-full border rounded px-2 py-1 text-sm"
        value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function SelectInput({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <div>
      <label className="block text-xs mb-1">{label}</label>
      <select className="w-full border rounded px-2 py-1 text-sm"
        value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o}>{o}</option>)}
      </select>
    </div>
  );
}

function CheckInput({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
