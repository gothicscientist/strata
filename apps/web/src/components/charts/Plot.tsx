"use client";

import dynamic from "next/dynamic";
import type { PlotParams } from "react-plotly.js/factory";

/** Plotly, loaded on the client only (it touches window at import time). */
export const Plot = dynamic<PlotParams>(
  async () => {
    const [{ default: createPlotlyComponent }, { default: Plotly }] = await Promise.all([
      import("react-plotly.js/factory"),
      import("plotly.js-dist-min"),
    ]);
    return createPlotlyComponent(Plotly as never);
  },
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[24rem] items-center justify-center text-small text-ink-3 italic">
        Preparing figure&hellip;
      </div>
    ),
  },
);

export const SERIF = '"Archivo Variable", Archivo, system-ui, sans-serif';

/** Shared publication styling: thin black axes, no grid, serif labels. */
export function journalAxis(title: string, extra: Record<string, unknown> = {}) {
  return {
    title: { text: title, font: { family: SERIF, size: 14, color: "#1e2630" }, standoff: 8 },
    showgrid: false,
    zeroline: true,
    zerolinecolor: "#e3e7e4",
    zerolinewidth: 1,
    showline: true,
    linecolor: "#1e2630",
    linewidth: 0.75,
    mirror: false,
    ticks: "outside",
    ticklen: 4,
    tickwidth: 0.75,
    tickcolor: "#1e2630",
    tickfont: { family: SERIF, size: 12, color: "#444e59" },
    automargin: true,
    ...extra,
  };
}

export const journalLayout = {
  paper_bgcolor: "#ffffff",
  plot_bgcolor: "#ffffff",
  font: { family: SERIF, size: 13, color: "#1e2630" },
  hoverlabel: {
    bgcolor: "#ffffff",
    bordercolor: "#1e2630",
    font: { family: SERIF, size: 13, color: "#1e2630" },
    align: "left",
  },
  legend: {
    font: { family: SERIF, size: 12, color: "#444e59" },
    bgcolor: "rgba(255,255,255,0)",
    borderwidth: 0,
    itemsizing: "constant",
  },
  margin: { l: 56, r: 16, t: 12, b: 48 },
};

export const plotConfig = {
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"],
  toImageButtonOptions: { format: "svg", filename: "strata-figure" },
};
