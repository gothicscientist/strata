"use client";

import { scaleLinear } from "d3-scale";
import { useState } from "react";
import { useWidth } from "./useWidth";
import { sourceColor } from "@/lib/palette";

export interface WeightRow {
  label: string;
  weight: number;
  lo?: number | null;
  hi?: number | null;
}

const pctText = (v: number) => `${(v * 100).toFixed(1).replace("-", "−")}%`;

/**
 * Two-panel figure for mixture weights:
 * (a) a single 100% stacked bar of point estimates, direct-labelled;
 * (b) per-source estimates with interval whiskers on a shared 0-100% axis.
 * Weights outside [0, 1] (possible in qpAdm) extend the axis and break the stacked bar honestly.
 */
export function WeightsChart({
  rows,
  intervalLabel,
  title,
}: {
  rows: WeightRow[];
  intervalLabel: string;
  title: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const labelW = Math.min(220, Math.max(120, width * 0.28));
  const left = labelW + 12;
  const right = 24;
  const plotW = Math.max(120, width - left - right);

  const lo = Math.min(0, ...rows.map((r) => r.lo ?? r.weight));
  const hi = Math.max(1, ...rows.map((r) => r.hi ?? r.weight));
  const x = scaleLinear().domain([lo, hi]).range([0, plotW]).nice();
  const ticks = x.ticks(5);

  const allInRange = rows.every((r) => r.weight >= 0 && r.weight <= 1);
  const barH = 26;
  const rowH = 30;
  const stackTop = 8;
  const forestTop = allInRange ? stackTop + barH + 34 : 8;
  const height = forestTop + rows.length * rowH + 34;

  let cum = 0;
  const segments = rows.map((r, i) => {
    const s = { i, x0: cum, x1: cum + Math.max(0, r.weight) };
    cum += Math.max(0, r.weight);
    return s;
  });
  const stackScale = scaleLinear().domain([0, Math.max(1, cum)]).range([0, plotW]);

  return (
    <div ref={ref} className="relative">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`${title}. ${rows.map((r) => `${r.label} ${pctText(r.weight)}`).join(", ")}`}
        className="block overflow-visible font-serif"
      >
        {allInRange ? (
          <g transform={`translate(${left},${stackTop})`}>
            <text x={-12} y={barH / 2} dy="0.35em" textAnchor="end" fontSize={13} fill="#333" fontStyle="italic">
              (a) composition
            </text>
            {segments.map((s) => {
              const w = stackScale(s.x1) - stackScale(s.x0);
              const r = rows[s.i]!;
              return (
                <g key={r.label} onMouseEnter={() => setHover(s.i)} onMouseLeave={() => setHover(null)}>
                  <rect
                    x={stackScale(s.x0) + (s.i ? 1 : 0)}
                    y={0}
                    width={Math.max(0, w - (s.i ? 1 : 0) - 1)}
                    height={barH}
                    fill={sourceColor(s.i)}
                    opacity={hover === null || hover === s.i ? 1 : 0.45}
                  />
                  {w > 44 ? (
                    <text
                      x={stackScale(s.x0) + w / 2}
                      y={barH / 2}
                      dy="0.35em"
                      textAnchor="middle"
                      fontSize={12.5}
                      fill="#fff"
                      className="num"
                    >
                      {pctText(r.weight)}
                    </text>
                  ) : null}
                </g>
              );
            })}
          </g>
        ) : null}

        <g transform={`translate(${left},${forestTop})`}>
          {allInRange ? (
            <text x={-12} y={-12} textAnchor="end" fontSize={13} fill="#333" fontStyle="italic">
              (b) estimates
            </text>
          ) : null}
          {ticks.map((t) => (
            <line
              key={t}
              x1={x(t)}
              x2={x(t)}
              y1={0}
              y2={rows.length * rowH}
              stroke={t === 0 ? "#9a9a9a" : "#efefef"}
              strokeWidth={t === 0 ? 0.75 : 0.75}
            />
          ))}
          {rows.map((r, i) => {
            const cy = i * rowH + rowH / 2;
            const hasCi = r.lo !== null && r.lo !== undefined && r.hi !== null && r.hi !== undefined;
            return (
              <g
                key={r.label}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                opacity={hover === null || hover === i ? 1 : 0.5}
              >
                <rect x={-left} y={i * rowH} width={left + plotW + right} height={rowH} fill="transparent" />
                <text x={-12} y={cy} dy="0.35em" textAnchor="end" fontSize={13.5} fill="#000">
                  {r.label.length > 30 ? `${r.label.slice(0, 29)}…` : r.label}
                  <title>{r.label}</title>
                </text>
                {hasCi ? (
                  <>
                    <line x1={x(r.lo!)} x2={x(r.hi!)} y1={cy} y2={cy} stroke="#000" strokeWidth={1} />
                    <line x1={x(r.lo!)} x2={x(r.lo!)} y1={cy - 5} y2={cy + 5} stroke="#000" strokeWidth={1} />
                    <line x1={x(r.hi!)} x2={x(r.hi!)} y1={cy - 5} y2={cy + 5} stroke="#000" strokeWidth={1} />
                  </>
                ) : null}
                <rect
                  x={x(r.weight) - 4.5}
                  y={cy - 4.5}
                  width={9}
                  height={9}
                  fill={allInRange ? sourceColor(i) : "#000"}
                  stroke="#fff"
                  strokeWidth={1.5}
                />
              </g>
            );
          })}
          <line x1={0} x2={plotW} y1={rows.length * rowH} y2={rows.length * rowH} stroke="#000" strokeWidth={0.75} />
          {ticks.map((t) => (
            <g key={t} transform={`translate(${x(t)},${rows.length * rowH})`}>
              <line y2={4} stroke="#000" strokeWidth={0.75} />
              <text y={17} textAnchor="middle" fontSize={12} fill="#333" className="num">
                {Math.round(t * 100).toString().replace("-", "−")}%
              </text>
            </g>
          ))}
          <text x={plotW / 2} y={rows.length * rowH + 32} textAnchor="middle" fontSize={13} fill="#000">
            Mixture weight; whiskers: {intervalLabel}
          </text>
        </g>
      </svg>
      {hover !== null && rows[hover] ? (
        <div className="pointer-events-none absolute top-0 right-0 border border-ink bg-paper px-3 py-1.5 text-caption num">
          <span className="font-medium">{rows[hover]!.label}</span> {pctText(rows[hover]!.weight)}
          {rows[hover]!.lo !== null && rows[hover]!.lo !== undefined
            ? ` [${pctText(rows[hover]!.lo!)}, ${pctText(rows[hover]!.hi!)}]`
            : ""}
        </div>
      ) : null}
    </div>
  );
}
