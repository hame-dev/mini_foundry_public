"use client";
import ReactECharts from "echarts-for-react";
import { echartsTheme } from "@/lib/echartsTheme";

type Props = {
  rows?: Record<string, unknown>[];
  config: { label: string; value: string };
};

export default function PieChart({ rows, config }: Props) {
  const data = (rows || []).map((r) => ({
    name: String(r[config.label] ?? ""),
    value: Number(r[config.value] ?? 0),
  }));
  const t = echartsTheme();
  const option = {
    color: t.palette,
    textStyle: t.textStyle,
    tooltip: { trigger: "item", ...t.tooltip },
    legend: { bottom: 0, ...t.legend },
    series: [{ type: "pie", radius: ["35%", "65%"], data }],
  };
  return <ReactECharts option={option} style={{ height: "100%", width: "100%" }} />;
}
