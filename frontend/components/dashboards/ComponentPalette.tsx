"use client";
import { COMPONENT_LABELS, type ComponentType } from "@/lib/dashboards";

type Props = {
  onAdd: (type: ComponentType) => void;
};

export default function ComponentPalette({ onAdd }: Props) {
  const types = Object.keys(COMPONENT_LABELS) as ComponentType[];
  return (
    <div className="space-y-1">
      <h3 className="text-xs uppercase tracking-wide text-gray-500 mb-2">Add component</h3>
      {types.map((t) => (
        <button
          key={t}
          onClick={() => onAdd(t)}
          className="block w-full text-left px-3 py-2 text-sm border rounded hover:bg-gray-50"
        >
          {COMPONENT_LABELS[t]}
        </button>
      ))}
    </div>
  );
}
