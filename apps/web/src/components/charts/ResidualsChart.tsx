"use client";

import { scaleBand, scaleLinear } from "d3-scale";
import { useState } from "react";
import { useWidth } from "./useWidth";

export interface ResidualPoint {
  label: string;
  value: number;
  /** Optional standard error; drawn as a ±1.96 SE whisker. */
  se?: number | null;
}

/**
 * Lollipop chart of residuals around zero. Optional reference band (e.g. |z| = 2 for f4 residuals)
 * is drawn as two hairlines, not a filled area.
 */
export function ResidualsChart({
  points,
  yLabel,
  band,
  highlightAbove,
  title,
}: {
  points: ResidualPoint[];
  yLabel: string;
  band?: number;
  /** Points with |value| above this are drawn in the alert hue. */
  highlightAbove?: number;
  title: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const m = { l: 64, r: 12, t: 10, b: points.length > 14 ? 74 : 40 };
  const h = 240;
  const w = Math.max(200, width - m.l - m.r);
  const ext = Math.max(
    band ?? 0,
    ...points.map((p) => Math.abs(p.value) + (p.se ? 1.96 * p.se : 0)),
    1e-6,
  );
  const y = scaleLinear().domain([-ext * 1.1, ext * 1.1]).range([h, 0]).nice();
  const x = scaleBand<string>().domain(points.map((p, i) => `${i}`)).range([0, w]).padding(0.3);
  const tickFmt = y.tickFormat(5);
  const fmt = (v: number) => (Math.abs(v) >= 0.01 || v === 0 ? v.toFixed(3) : v.toExponential(1)).replace("-", "−");

  return (
    <div ref={ref} className="relative">
      <svg width={width} height={h + m.t + m.b} role="img" aria-label={title} className="block font-sans">
        <g transform={`translate(${m.l},${m.t})`}>
          {band ? (
            [band, -band].map((b) => (
              <line key={b} x1={0} x2={w} y1={y(b)} y2={y(b)} stroke="#9aa3a8" strokeWidth={0.75} strokeDasharray="3 3" />
            ))
          ) : null}
          <line x1={0} x2={w} y1={y(0)} y2={y(0)} stroke="#1e2630" strokeWidth={0.75} />
          {points.map((p, i) => {
            const cx = (x(`${i}`) ?? 0) + x.bandwidth() / 2;
            const out = highlightAbove !== undefined && Math.abs(p.value) > highlightAbove;
            return (
              <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                <rect x={x(`${i}`)} y={0} width={x.bandwidth()} height={h} fill="transparent" />
                {p.se ? (
                  <line
                    x1={cx}
                    x2={cx}
                    y1={y(p.value - 1.96 * p.se)}
                    y2={y(p.value + 1.96 * p.se)}
                    stroke="#9aa3a8"
                    strokeWidth={1}
                  />
                ) : null}
                <line x1={cx} x2={cx} y1={y(0)} y2={y(p.value)} stroke="#1e2630" strokeWidth={hover === i ? 2 : 1.25} />
                <circle cx={cx} cy={y(p.value)} r={4} fill={out ? "#a13f5e" : "#1e2630"} stroke="#fff" strokeWidth={1.5} />
              </g>
            );
          })}
          <line x1={0} x2={0} y1={0} y2={h} stroke="#1e2630" strokeWidth={0.75} />
          {y.ticks(5).map((t) => (
            <g key={t} transform={`translate(0,${y(t)})`}>
              <line x2={-4} stroke="#1e2630" strokeWidth={0.75} />
              <text x={-7} dy="0.35em" textAnchor="end" fontSize={12} fill="#444e59" className="num">
                {tickFmt(t).replace("-", "\u2212")}
              </text>
            </g>
          ))}
          {points.map((p, i) => {
            const cx = (x(`${i}`) ?? 0) + x.bandwidth() / 2;
            const rotate = points.length > 14;
            return (
              <text
                key={i}
                transform={`translate(${cx},${h + 14}) ${rotate ? "rotate(-50)" : ""}`}
                textAnchor={rotate ? "end" : "middle"}
                fontSize={11.5}
                fill="#444e59"
              >
                {p.label}
              </text>
            );
          })}
          <text transform={`translate(${-50},${h / 2}) rotate(-90)`} textAnchor="middle" fontSize={13}>
            {yLabel}
          </text>
        </g>
      </svg>
      {hover !== null && points[hover] ? (
        <div className="pointer-events-none absolute top-0 right-0 border border-ink bg-paper px-3 py-1.5 text-caption num">
          <span className="font-medium">{points[hover]!.label}</span> {fmt(points[hover]!.value)}
          {points[hover]!.se ? ` (SE ${fmt(points[hover]!.se!)})` : ""}
        </div>
      ) : null}
    </div>
  );
}
