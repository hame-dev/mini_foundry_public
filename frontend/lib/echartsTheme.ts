"use client";

/**
 * Theme-aware ECharts defaults. ECharts' built-in text color (~#333) is
 * unreadable on the dark surface, so we read the live design tokens off the
 * document root and feed them into axis/legend/tooltip defaults. Re-reads on
 * each call, so charts pick up the right palette when they (re)mount.
 */
export type EchartsThemeDefaults = {
  textStyle: { color: string };
  categoryAxis: Record<string, unknown>;
  valueAxis: Record<string, unknown>;
  legend: { textStyle: { color: string } };
  tooltip: Record<string, unknown>;
  palette: string[];
};

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function echartsTheme(): EchartsThemeDefaults {
  const text = cssVar("--text-2", "#aeb9c6");
  const muted = cssVar("--muted", "#8593a1");
  const line = cssVar("--line", "#2a323d");
  const panel = cssVar("--panel", "#161b22");
  const accent = cssVar("--accent", "#4a9eff");
  const teal = cssVar("--teal", "#2bb6b2");
  const warning = cssVar("--warning", "#e0a64b");
  const danger = cssVar("--danger", "#f0616d");
  const branch = cssVar("--branch", "#b083f0");

  const axisCommon = {
    axisLine: { lineStyle: { color: line } },
    axisTick: { lineStyle: { color: line } },
    axisLabel: { color: muted },
    splitLine: { lineStyle: { color: line } },
  };

  return {
    textStyle: { color: text },
    categoryAxis: { ...axisCommon, splitLine: { show: false } },
    valueAxis: axisCommon,
    legend: { textStyle: { color: text } },
    tooltip: {
      backgroundColor: panel,
      borderColor: line,
      textStyle: { color: text },
    },
    palette: [accent, teal, warning, danger, branch, "#5fb878"],
  };
}
