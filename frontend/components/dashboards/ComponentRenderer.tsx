"use client";
import type { ComponentRender, DashboardComponent } from "@/lib/dashboards";
import MetricCard from "./components/MetricCard";
import DataTable from "./components/DataTable";
import LineChart from "./components/LineChart";
import BarChart from "./components/BarChart";
import PieChart from "./components/PieChart";
import Markdown from "./components/Markdown";

type Props = {
  component: DashboardComponent;
  render?: ComponentRender;
  onFilterUpdate?: (filterId: string, value: unknown) => void;
  filters?: Record<string, any>;
};

export default function ComponentRenderer({ component, render, onFilterUpdate, filters }: Props) {
  let title = component.title;
  if (title && filters) {
    title = title.replace(/\{\{([^}]+)\}\}/g, (_, key) => {
      const trimmed = key.trim();
      return filters[trimmed] !== undefined ? String(filters[trimmed]) : `{{${trimmed}}}`;
    });
  }

  if (render?.error) {
    return (
      <div className="h-full flex flex-col">
        {title && <div className="px-3 pt-2 text-xs font-medium" style={{ color: "var(--muted)" }}>{title}</div>}
        <div className="flex-1 flex items-center justify-center text-xs" style={{ color: "var(--muted)", background: "var(--bg-2)" }}>
          {render.error.startsWith("permission_denied") ? "Access denied" : render.error}
        </div>
      </div>
    );
  }

  const rows = render?.rows;
  const columns = render?.columns;

  let body: React.ReactNode = null;
  switch (component.component_type) {
    case "metric_card":
      body = <MetricCard title={title} rows={rows} config={component.config as never} />;
      break;
    case "table":
    case "data_table":
    case "object_table":
      body = <DataTable
        columns={columns}
        rows={rows}
        config={component.config as never}
        actions={(component as { actions?: import("@/lib/actions").DashboardAction[] }).actions}
        onFilterUpdate={onFilterUpdate}
      />;
      break;
    case "chart_xy":
      body = <BarChart rows={rows} config={component.config as never} />;
      break;
    case "filter_list":
      body = (
        <div className="p-3 text-xs" style={{ color: "var(--text-2)" }}>
          {(rows ?? []).slice(0, 6).map((row, i) => (
            <div key={i} className="flex items-center justify-between border-b py-2">
              <span>{String(Object.values(row)[0] ?? `Option ${i + 1}`)}</span>
              <span className="badge">{String(Object.values(row)[1] ?? "")}</span>
            </div>
          ))}
          {!rows?.length ? "Filter list widget" : null}
        </div>
      );
      break;
    case "button_group":
      body = (
        <div className="p-3 flex flex-wrap gap-2">
          {((component.config.buttons as Array<{ label?: string }> | undefined) ?? [{ label: "Action" }]).map((button, i) => (
            <button key={i} className={i === 0 ? "btn-primary" : "btn-ghost"}>{button.label ?? `Action ${i + 1}`}</button>
          ))}
        </div>
      );
      break;
    case "map":
      body = (
        <div className="h-full grid place-items-center" style={{ background: "var(--bg-2)", color: "var(--muted)" }}>
          <div className="text-center">
            <div className="text-3xl">⌖</div>
            <div className="text-xs">Map widget</div>
          </div>
        </div>
      );
      break;
    case "line_chart":
      body = <LineChart rows={rows} config={component.config as never} />;
      break;
    case "bar_chart":
      body = <BarChart rows={rows} config={component.config as never} />;
      break;
    case "pie_chart":
      body = <PieChart rows={rows} config={component.config as never} />;
      break;
    case "markdown":
      body = <Markdown config={component.config as never} />;
      break;
    case "filter_date":
    case "filter_select":
      // Filters are rendered by FilterBar, not on the grid.
      body = <div className="p-3 text-xs text-gray-500">Filter (configured in toolbar)</div>;
      break;
    default:
      body = <div className="p-3 text-xs text-red-600">Unknown component {component.component_type}</div>;
  }

  return (
    <div className="app-card h-full flex flex-col overflow-hidden">
      {title && <div className="px-3 py-2 text-xs font-medium" style={{ color: "var(--text-2)", borderBottom: "1px solid var(--line)" }}>{title}</div>}
      <div className="flex-1 overflow-hidden">{body}</div>
    </div>
  );
}
