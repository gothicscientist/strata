"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useWidth } from "./useWidth";
import { Caveman } from "../Caveman";
import { bpRange, int } from "@/lib/format";
import { periodStyle, type Lithology, type PeriodStyle } from "@/lib/periods";

export interface Layer {
  period: string;
  populations: number;
  individuals: number;
  minBp: number | null;
  maxBp: number | null;
}

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

/** Lithology symbols, after the conventions of a measured geological section. */
function PatternMarks({ kind, mark }: { kind: Lithology; mark: string }) {
  const s = { stroke: mark, strokeWidth: 1, fill: "none" } as const;
  switch (kind) {
    case "soil":
      return (
        <>
          <circle cx={3} cy={4} r={0.8} fill={mark} />
          <circle cx={10} cy={11} r={0.8} fill={mark} />
          <path d="M8 3h3M1 10h2" {...s} />
        </>
      );
    case "sand":
      return (
        <>
          {[
            [2, 2],
            [7, 4],
            [12, 1],
            [4, 8],
            [10, 9],
            [1, 13],
            [7, 12],
            [13, 13],
          ].map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r={0.65} fill={mark} />
          ))}
        </>
      );
    case "silt":
      return <path d="M1 4h5M9 4h4M4 11h5M12 11h2" {...s} />;
    case "brick":
      return <path d="M0 0.5h14M0 7.5h14M3 0.5v7M10 7.5v7" {...s} />;
    case "hatch":
      return <path d="M-2 4L4 -2M-2 11L11 -2M3 16L16 3M10 16L16 10" {...s} />;
    case "cross":
      return <path d="M0 0L14 14M14 0L0 14M7 -7L21 7M-7 7L7 21" {...s} strokeWidth={0.8} />;
    case "shale":
      return <path d="M0 3.5h8M10 3.5h4M4 10.5h8" {...s} />;
    case "gravel":
      return (
        <>
          <ellipse cx={4} cy={4} rx={2.2} ry={1.6} {...s} />
          <ellipse cx={11} cy={11} rx={1.8} ry={1.4} {...s} />
        </>
      );
    case "tick":
      return <path d="M3 2v4M10 9v4M10 1v2M3 10v2" {...s} />;
    default:
      return null;
  }
}

export function LithologyDefs({ periods }: { periods: PeriodStyle[] }) {
  return (
    <defs>
      {periods.map((p) => (
        <pattern key={p.name} id={`lith-${slug(p.name)}`} width={14} height={14} patternUnits="userSpaceOnUse">
          <rect width={14} height={14} fill={p.color} />
          <PatternMarks kind={p.lithology} mark={p.mark} />
        </pattern>
      ))}
    </defs>
  );
}

/**
 * The reference library drawn as a drilled core: one layer per period, youngest at the surface.
 * Layer thickness grows with the square root of the number of populations, with a floor so a
 * period holding one population is still legible.
 */
export function CoreSample({ layers, height = 520, digger = false }: { layers: Layer[]; height?: number; digger?: boolean }) {
  const router = useRouter();
  const [hover, setHover] = useState<string | null>(null);
  // Tapping the surface of the core shakes it and lets the layers settle again.
  const [quakes, setQuakes] = useState(0);
  const [ref, width] = useWidth<HTMLDivElement>(420);
  const narrow = width < 440;
  const floor = 42;
  const free = Math.max(0, height - floor * layers.length);
  const roots = layers.map((l) => Math.sqrt(l.populations));
  const sum = roots.reduce((a, b) => a + b, 0) || 1;
  let y = 0;
  const placed = layers.map((l, i) => {
    const h = floor + (free * roots[i]!) / sum;
    const out = { ...l, y, h, style: periodStyle(l.period) };
    y += h;
    return out;
  });
  const total = y;
  const coreW = narrow ? 64 : 116;
  const cap = 9; // half-height of the elliptical cap at the surface
  const n = placed.length;

  // Boundaries between layers wobble a little, as real contacts do; deterministic per index.
  const contact = (yy: number, i: number) => {
    const a = 2.2 * Math.sin(i * 1.7 + 0.6);
    const b = 1.6 * Math.cos(i * 2.3);
    return `M0 ${yy + a} C ${coreW * 0.3} ${yy - b} ${coreW * 0.65} ${yy + b + a * 0.5} ${coreW} ${yy - a * 0.4}`;
  };

  const href = (p: string) => `/library/?period=${encodeURIComponent(p)}`;

  // The digger stands on the surface; his feet (y 77 of 80 in his drawing) meet its middle.
  const manH = narrow ? 66 : 80;
  const lift = digger ? Math.round(manH * 0.9) : 0;
  const manTop = lift + cap - (77 / 80) * manH;

  return (
    <div className="relative" style={{ paddingTop: lift }}>
    {digger ? (
      <Caveman
        pose="dig"
        size={manH}
        label="Shake the core"
        onPoke={() => setQuakes((q) => q + 1)}
        className="absolute z-10"
        style={{ top: manTop, left: coreW / 2 - manH * 0.4 + 4 }}
      />
    ) : null}
    <div ref={ref} className="relative" style={{ height: total + cap * 2 + 8 }}>
      <div key={quakes} className="absolute inset-0" style={{ animation: quakes ? "strata-quake 620ms ease-out" : undefined }}>
      <svg
        width={coreW + 24}
        height={total + cap * 2 + 8}
        className="absolute top-0 left-0 overflow-visible"
        role="img"
        aria-label={`Reference library by period: ${placed.map((p) => `${p.period}, ${p.populations} populations`).join("; ")}`}
      >
        <LithologyDefs periods={placed.map((p) => p.style)} />
        <defs>
          <linearGradient id="core-shade" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor="#1e2630" stopOpacity="0.22" />
            <stop offset="0.18" stopColor="#1e2630" stopOpacity="0.02" />
            <stop offset="0.42" stopColor="#fff" stopOpacity="0.2" />
            <stop offset="0.7" stopColor="#1e2630" stopOpacity="0.03" />
            <stop offset="1" stopColor="#1e2630" stopOpacity="0.3" />
          </linearGradient>
          <clipPath id="core-clip">
            <path d={`M0 ${cap} V ${total + cap} A ${coreW / 2} ${cap} 0 0 0 ${coreW} ${total + cap} V ${cap} Z`} />
          </clipPath>
        </defs>
        <g clipPath="url(#core-clip)">
          {placed.map((p, i) => (
            <g
              key={p.period}
              style={{
                transformBox: "fill-box",
                transformOrigin: "50% 100%",
                animation: `strata-deposit 520ms cubic-bezier(.2,.7,.2,1) ${(n - 1 - i) * 85}ms both`,
              }}
            >
              <path
                d={`${contact(p.y + cap, i)} V ${p.y + p.h + cap + 6} H 0 Z`}
                fill={`url(#lith-${slug(p.period)})`}
                className="cursor-pointer"
                onMouseEnter={() => setHover(p.period)}
                onMouseLeave={() => setHover(null)}
                onClick={() => router.push(href(p.period))}
              />
              {i > 0 ? (
                <path d={contact(p.y + cap, i)} fill="none" stroke="#1e2630" strokeOpacity={0.35} strokeWidth={0.8} />
              ) : null}
            </g>
          ))}
          <rect x={0} y={0} width={coreW} height={total + cap * 2} fill="url(#core-shade)" pointerEvents="none" />
          {hover
            ? (() => {
                const p = placed.find((q) => q.period === hover);
                return p ? (
                  <rect x={0} y={p.y + cap} width={coreW} height={p.h} fill="#fff" fillOpacity={0.18} pointerEvents="none" />
                ) : null;
              })()
            : null}
          {/* Grains still settling through the youngest layer. */}
          {placed[0]
            ? [0.14, 0.31, 0.47, 0.6, 0.73, 0.88].map((fx, k) => (
                <circle
                  key={fx}
                  cx={coreW * fx}
                  cy={cap + 2}
                  r={k % 2 ? 1 : 1.4}
                  fill={placed[0]!.style.mark}
                  pointerEvents="none"
                  style={
                    {
                      "--fall": `${placed[0]!.h - 6}px`,
                      animation: `strata-grain ${4.2 + (k % 3) * 1.3}s linear ${1.4 + k * 0.9}s infinite both`,
                    } as React.CSSProperties
                  }
                />
              ))
            : null}
        </g>
        {/* The hovered layer slides out of the core like a sample chip being pulled. */}
        {hover
          ? (() => {
              const i = placed.findIndex((q) => q.period === hover);
              const p = placed[i];
              if (!p) return null;
              return (
                <g key={hover} pointerEvents="none" style={{ animation: "strata-pull 240ms cubic-bezier(.2,.9,.3,1.2) both" }}>
                  <clipPath id="pull-clip">
                    <rect x={0} y={p.y + cap} width={coreW} height={p.h} rx={2} />
                  </clipPath>
                  <g clipPath="url(#pull-clip)" style={{ filter: "drop-shadow(3px 3px 0 rgba(30,38,48,.25))" }}>
                    <rect x={0} y={p.y + cap} width={coreW} height={p.h} fill={`url(#lith-${slug(p.period)})`} />
                    <rect x={0} y={p.y + cap} width={coreW} height={p.h} fill="url(#core-shade)" />
                    <rect x={0.5} y={p.y + cap + 0.5} width={coreW - 1} height={p.h - 1} fill="none" stroke="#1e2630" strokeOpacity={0.5} />
                  </g>
                </g>
              );
            })()
          : null}
        {/* Surface of the core */}
        <ellipse cx={coreW / 2} cy={cap} rx={coreW / 2} ry={cap} fill={placed[0]?.style.color ?? "#ddd"} />
        <ellipse
          cx={coreW / 2}
          cy={cap}
          rx={coreW / 2}
          ry={cap}
          fill="#fff"
          fillOpacity={0.35}
          stroke="#1e2630"
          strokeOpacity={0.25}
          strokeWidth={0.8}
          className="cursor-pointer"
          onClick={() => setQuakes((q) => q + 1)}
        >
          <title>Tap the surface</title>
        </ellipse>
        {/* Ticks to the labels */}
        {placed.map((p) => (
          <line
            key={p.period}
            x1={coreW + 4}
            x2={coreW + 20}
            y1={p.y + cap + p.h / 2}
            y2={p.y + cap + p.h / 2}
            stroke="#1e2630"
            strokeOpacity={hover === p.period ? 0.9 : 0.35}
            strokeWidth={1}
          />
        ))}
      </svg>

      <ol className="absolute top-0 right-0" style={{ left: coreW + 30 }}>
        {placed.map((p, i) => (
          <li
            key={p.period}
            className="absolute right-0 left-0 flex items-center"
            style={{
              top: p.y + cap,
              height: p.h,
              animation: `strata-label 420ms ease-out ${(n - 1 - i) * 85 + 200}ms both`,
            }}
          >
            <Link
              href={href(p.period)}
              onMouseEnter={() => setHover(p.period)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(p.period)}
              onBlur={() => setHover(null)}
              className={`-mx-2 grid w-full grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 rounded-[6px] px-2 py-1 no-underline transition-[background-color,transform] duration-200 ${
                hover === p.period ? "translate-x-2 bg-panel" : ""
              }`}
            >
              <span className="min-w-0">
                <span className="block truncate text-[1.08rem] leading-tight font-semibold text-ink">{p.period}</span>
                <span className="num block truncate text-[0.86rem] leading-snug text-ink-3">
                  {bpRange(p.minBp, p.maxBp)}
                </span>
              </span>
              <span className="num text-right text-[0.9rem] leading-tight text-ink-2">
                <span className="text-[1.2rem] font-semibold text-ink">{p.populations}</span>{" "}
                {p.populations === 1 ? "population" : "populations"}
                <span className="block text-[0.82rem] text-ink-3">{int(p.individuals)} individuals</span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
      </div>
    </div>
    </div>
  );
}
