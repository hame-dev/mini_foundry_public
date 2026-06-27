"use client";
import GridLayout, { Layout } from "react-grid-layout";
import { useEffect, useRef, useState } from "react";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import type { ComponentRender, DashboardComponent } from "@/lib/dashboards";
import ComponentRenderer from "./ComponentRenderer";

type Props = {
  components: DashboardComponent[];
  renders: Record<string, ComponentRender | undefined>;
  editable: boolean;
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  onLayoutChange?: (positions: Record<string, { x: number; y: number; w: number; h: number }>) => void;
  cols?: number;
  rowHeight?: number;
  width?: number;
  onFilterUpdate?: (filterId: string, value: unknown) => void;
  filters?: Record<string, any>;
};

export default function DashboardCanvas({
  components, renders, editable, selectedId, onSelect, onLayoutChange,
  cols = 12, rowHeight = 60, width = 1100,
  onFilterUpdate, filters,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [actualWidth, setActualWidth] = useState(width);
  useEffect(() => {
    function measure() {
      if (wrapRef.current) setActualWidth(Math.max(320, wrapRef.current.clientWidth));
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  const layout: Layout[] = components.map((c) => ({
    i: c.id, x: c.position.x, y: c.position.y, w: c.position.w, h: c.position.h,
  }));

  function handleLayoutChange(next: Layout[]) {
    if (!onLayoutChange) return;
    const out: Record<string, { x: number; y: number; w: number; h: number }> = {};
    for (const it of next) out[it.i] = { x: it.x, y: it.y, w: it.w, h: it.h };
    onLayoutChange(out);
  }

  return (
    <div ref={wrapRef} style={{ width: "100%" }}>
      <GridLayout
        className="layout"
        layout={layout}
        cols={cols}
        rowHeight={rowHeight}
        width={actualWidth}
        isDraggable={editable}
        isResizable={editable}
        onLayoutChange={handleLayoutChange}
        draggableCancel="input,textarea,button,select,.no-drag"
      >
        {components.map((c) => (
          <div
            key={c.id}
            onClick={() => onSelect?.(c.id)}
            className={selectedId === c.id ? "ring-2 ring-blue-500 rounded" : ""}
          >
            <ComponentRenderer
              component={c}
              render={renders[c.id]}
              onFilterUpdate={onFilterUpdate}
              filters={filters}
            />
          </div>
        ))}
      </GridLayout>
    </div>
  );
}
