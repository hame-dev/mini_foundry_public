"use client";
import ReactECharts from "echarts-for-react";
import { echartsTheme } from "@/lib/echartsTheme";

type Props = {
  rows?: Record<string, unknown>[];
  config: { x: string; y: string | string[] };
};

export default function LineChart({ rows, config }: Props) {
  const data = rows || [];
  const ys = Array.isArray(config.y) ? config.y : [config.y];
  const t = echartsTheme();
  const option = {
    color: t.palette,
    textStyle: t.textStyle,
    tooltip: { trigger: "axis", ...t.tooltip },
    grid: { left: 40, right: 16, top: 24, bottom: 30 },
    xAxis: { type: "category", data: data.map((r) => String(r[config.x] ?? "")), ...t.categoryAxis },
    yAxis: { type: "value", ...t.valueAxis },
    legend: ys.length > 1 ? { top: 0, ...t.legend } : undefined,
    series: ys.map((y) => ({
      type: "line",
      name: y,
      data: data.map((r) => Number(r[y] ?? 0)),
      smooth: true,
    })),
  };
  return <ReactECharts option={option} style={{ height: "100%", width: "100%" }} />;
}
