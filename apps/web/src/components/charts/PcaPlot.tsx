"use client";

import { useId, useMemo, useState } from "react";
import { Plot, journalAxis, journalLayout, plotConfig, SERIF } from "./Plot";
import { regionSlots, OTHER } from "@/lib/palette";
import type { CoordinateSpaceInfo, ProjectedPoint } from "@/lib/types";

export interface PcaPlotProps {
  space: CoordinateSpaceInfo;
  targets?: ProjectedPoint[];
  height?: number;
  /** Compact mode hides axis pickers and the legend (used on the landing page). */
  compact?: boolean;
  highlight?: string[];
}

export function pcLabel(space: CoordinateSpaceInfo, i: number): string {
  const ev = space.explained_variance?.[i];
  return ev !== undefined && ev !== null ? `PC${i + 1} (${(ev * 100).toFixed(1)}%)` : `PC${i + 1}`;
}

export function PcaPlot({ space, targets = [], height = 520, compact = false, highlight = [] }: PcaPlotProps) {
  const [x, setX] = useState(0);
  const [y, setY] = useState(1);
  const idBase = useId();
  const dims = Math.max(2, space.n_dims);

  const traces = useMemo(() => {
    const slots = regionSlots(space.populations.map((p) => ({ region: p.region })));
    const groups = new Map<string, typeof space.populations>();
    for (const p of space.populations) {
      const key = p.region ?? "Unassigned";
      const slot = slots.get(key);
      const g = slot && slot.color === OTHER ? "Other regions" : key;
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g)!.push(p);
    }
    const order = [...groups.keys()].sort((a, b) => {
      if (a === "Other regions") return 1;
      if (b === "Other regions") return -1;
      return (groups.get(b)!.length - groups.get(a)!.length) || a.localeCompare(b);
    });
    const hl = new Set(highlight);
    const ref = order.map((g) => {
      const pts = groups.get(g)!;
      const slot = g === "Other regions" ? { color: OTHER, symbol: "circle" } : slots.get(g)!;
      return {
        type: "scatter",
        mode: "markers",
        name: g,
        x: pts.map((p) => p.coords[x] ?? null),
        y: pts.map((p) => p.coords[y] ?? null),
        text: pts.map((p) => `${p.name}<br>${p.region ?? "Unassigned"}, n = ${p.n_samples}`),
        hovertemplate: "%{text}<extra></extra>",
        marker: {
          color: slot.color,
          symbol: slot.symbol,
          size: compact ? 5 : 7,
          opacity: 0.78,
          line: { width: pts.map((p) => (hl.has(p.population_id) ? 1.5 : 0)), color: "#1e2630" },
        },
      };
    });
    const tgt = targets.length
      ? [
          {
            type: "scatter",
            mode: "markers+text",
            name: targets.length === 1 ? "Target" : "Targets",
            x: targets.map((t) => t.coords[x] ?? null),
            y: targets.map((t) => t.coords[y] ?? null),
            text: targets.map((t) => t.name),
            textposition: "top right",
            textfont: { family: SERIF, size: 14, color: "#1e2630" },
            hovertemplate: "%{text} (projected)<extra></extra>",
            marker: { color: "#1e2630", symbol: "star", size: 15, line: { color: "#fff", width: 1.5 } },
          },
        ]
      : [];
    return [...ref, ...tgt];
  }, [space, targets, x, y, compact, highlight]);

  return (
    <div>
      {!compact && dims > 2 ? (
        <div className="mb-3 flex flex-wrap items-end gap-6 text-small">
          {(
            [
              ["Horizontal axis", x, setX],
              ["Vertical axis", y, setY],
            ] as const
          ).map(([label, value, set]) => (
            <label key={label} className="w-40" htmlFor={`${idBase}-${label}`}>
              <span className="label">{label}</span>
              <select
                id={`${idBase}-${label}`}
                className="field"
                value={value}
                onChange={(e) => set(Number(e.target.value))}
              >
                {Array.from({ length: dims }, (_, i) => (
                  <option key={i} value={i}>
                    {pcLabel(space, i)}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      ) : null}
      <Plot
        data={traces}
        layout={{
          ...journalLayout,
          height,
          margin: { ...journalLayout.margin, t: compact ? 12 : 36 },
          showlegend: true,
          legend: compact
            ? { ...journalLayout.legend, orientation: "h", x: 0, y: -0.22, xanchor: "left", yanchor: "top" }
            : { ...journalLayout.legend, orientation: "v", x: 1.01, y: 1, xanchor: "left" },
          xaxis: journalAxis(pcLabel(space, x)),
          yaxis: journalAxis(pcLabel(space, y), { scaleanchor: undefined }),
          hovermode: "closest",
          dragmode: compact ? false : "zoom",
        }}
        config={{ ...plotConfig, displayModeBar: compact ? false : "hover" }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  );
}
