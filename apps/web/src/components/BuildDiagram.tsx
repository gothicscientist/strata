"use client";

import { useEffect, useState } from "react";
import { useWidth } from "./charts/useWidth";
import { Term } from "./Term";
import { useSeen } from "@/lib/useSeen";
import { int } from "@/lib/format";

/* ------------------------------------------------------------------------------------------
 * How Strata is put together, as a small wiring diagram. Each box opens one line on what that
 * part does and how. Wires carry moving dashes so the direction of data is visible.
 * ---------------------------------------------------------------------------------------- */

type Id = "file" | "parse" | "vault" | "engine" | "admix" | "report" | "ref" | "assistant";
type Side = "l" | "r" | "t" | "b";

interface Node {
  title: string;
  sub: string;
  detail: React.ReactNode;
}

const NODES: Record<Id, Node> = {
  file: {
    title: "Your file",
    sub: "4 formats",
    detail: "23andMe, AncestryDNA, VCF or G25 coordinates. Checked for size and type before anything reads it.",
  },
  parse: {
    title: "Parser",
    sub: "Python",
    detail: (
      <>
        Reads each format, then lines every <Term k="snp" /> up with the reference panel: alleles matched, strand
        flips fixed, ambiguous A/T and C/G sites dropped. A QC report says how much was kept.
      </>
    ),
  },
  vault: {
    title: "Encrypted store",
    sub: "AES-256-GCM",
    detail:
      "Each dataset gets its own key, wrapped by a master key kept apart. Deleting that one key makes every copy unreadable, backups included. Guest data goes after 24 hours.",
  },
  engine: {
    title: "Analysis engine",
    sub: "Python, NumPy",
    detail: (
      <>
        <Term k="pca" /> projection, f2, f3 and <Term k="f4">f4</Term> statistics with{" "}
        <Term k="jackknife">block-jackknife</Term> errors, and an exact mixture solver, written from the published
        formulas (Patterson et al. 2012) with tests for each.
      </>
    ),
  },
  admix: {
    title: "ADMIXTOOLS 2",
    sub: "R",
    detail: (
      <>
        <Term k="qpadm" /> and qpWave, the standard tools of the field, run on f2 statistics precomputed once from the
        reference, so a test never has to start from raw genotypes.
      </>
    ),
  },
  report: {
    title: "Report",
    sub: "with provenance",
    detail:
      "Every result records its inputs, parameters, data release and software versions, so anyone can rerun it and get the same answer.",
  },
  ref: {
    title: "Reference library",
    sub: "AADR v66.p1",
    detail: (
      <>
        Published ancient genomes from the <Term k="aadr" />, plus present-day South Asians from 1000 Genomes,
        rebuilt from the raw release by a scripted pipeline.
      </>
    ),
  },
  assistant: {
    title: "Assistant",
    sub: "14 tools",
    detail:
      "A language model that answers by calling the same tools you use: search the library, run a fit, read a result. It only ever sees summaries, never genotypes.",
  },
};

/** Two layouts: a wide one in two rows and a narrow one in two columns. Centres in SVG units. */
const WIDE = {
  w: 820,
  h: 236,
  box: [128, 50] as readonly [number, number],
  at: {
    file: [72, 40],
    parse: [236, 40],
    vault: [400, 40],
    engine: [570, 40],
    admix: [742, 40],
    report: [742, 190],
    ref: [570, 190],
    assistant: [318, 190],
  } as Record<Id, readonly [number, number]>,
};
const NARROW = {
  w: 360,
  h: 590,
  box: [138, 48] as readonly [number, number],
  at: {
    file: [92, 40],
    parse: [92, 135],
    vault: [92, 230],
    engine: [92, 325],
    admix: [92, 445],
    report: [92, 545],
    ref: [272, 230],
    assistant: [272, 445],
  } as Record<Id, readonly [number, number]>,
};

interface Edge {
  from: Id;
  to: Id;
  wide: [Side, Side, number?, number?];
  narrow: [Side, Side, number?, number?];
  kind?: "summary";
}

const EDGES: Edge[] = [
  { from: "file", to: "parse", wide: ["r", "l"], narrow: ["b", "t"] },
  { from: "parse", to: "vault", wide: ["r", "l"], narrow: ["b", "t"] },
  { from: "vault", to: "engine", wide: ["r", "l"], narrow: ["b", "t"] },
  { from: "ref", to: "engine", wide: ["t", "b"], narrow: ["b", "r", 0, -12] },
  { from: "engine", to: "admix", wide: ["r", "l"], narrow: ["b", "t"] },
  { from: "admix", to: "report", wide: ["b", "t"], narrow: ["b", "t"] },
  { from: "engine", to: "report", wide: ["b", "l", 40, 0], narrow: ["l", "l", 0, 0] },
  { from: "assistant", to: "engine", wide: ["r", "b", 0, -40], narrow: ["t", "r", 0, 12], kind: "summary" },
];

const NORMAL: Record<Side, [number, number]> = { l: [-1, 0], r: [1, 0], t: [0, -1], b: [0, 1] };

function anchor(c: readonly [number, number], box: readonly [number, number], side: Side, off = 0): [number, number] {
  const [x, y] = c;
  const [w, h] = box;
  if (side === "l") return [x - w / 2, y + off];
  if (side === "r") return [x + w / 2, y + off];
  if (side === "t") return [x + off, y - h / 2];
  return [x + off, y + h / 2];
}

function geometry(e: Edge, L: typeof WIDE) {
  const [s0, s1, o0, o1] = L === WIDE ? e.wide : e.narrow;
  const p0 = anchor(L.at[e.from], L.box, s0, o0);
  const p1 = anchor(L.at[e.to], L.box, s1, o1);
  // A wire leaving and entering on the same side loops out only a little, to stay inside the frame.
  const k = s0 === s1 ? 20 : Math.max(34, Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) * 0.4);
  const n0 = NORMAL[s0];
  const n1 = NORMAL[s1];
  const c0: [number, number] = [p0[0] + n0[0] * k, p0[1] + n0[1] * k];
  const c1: [number, number] = [p1[0] + n1[0] * k, p1[1] + n1[1] * k];
  const mid: [number, number] = [
    0.125 * p0[0] + 0.375 * c0[0] + 0.375 * c1[0] + 0.125 * p1[0],
    0.125 * p0[1] + 0.375 * c0[1] + 0.375 * c1[1] + 0.125 * p1[1],
  ];
  return { d: `M${p0[0]} ${p0[1]} C${c0[0]} ${c0[1]} ${c1[0]} ${c1[1]} ${p1[0]} ${p1[1]}`, end: p1, n1, mid };
}

function CountUp({ to, run }: { to: number; run: boolean }) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!run) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setV(to);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const f = Math.min(1, (t - t0) / 1400);
      setV(Math.round(to * (1 - Math.pow(1 - f, 3))));
      if (f < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to, run]);
  return <>{int(v)}</>;
}

export interface BuildStats {
  snps?: number | null;
  populations?: number | null;
  projected?: number | null;
}

export function BuildDiagram({ stats }: { stats: BuildStats }) {
  const [wrap, width] = useWidth<HTMLDivElement>(820);
  const [seenRef, seen] = useSeen<HTMLDivElement>(0.25);
  const [sel, setSelected] = useState<Id>("engine");
  // Until someone points at a box, the others glow in turn to show they can be opened.
  const [touched, setTouched] = useState(false);
  const setSel = (id: Id) => {
    setSelected(id);
    setTouched(true);
  };
  const L = width < 620 ? NARROW : WIDE;
  const linked = (e: Edge) => e.from === sel || e.to === sel;

  const figures: Array<[number | null | undefined, string]> = [
    [stats.snps, "DNA positions compared"],
    [stats.projected, "ancient people placed"],
    [stats.populations, "reference populations"],
    [490, "automated tests"],
  ];

  return (
    <div ref={seenRef}>
      <dl className="mb-8 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
        {figures
          .filter((f): f is [number, string] => typeof f[0] === "number")
          .map(([n, label]) => (
            <div key={label} className="border-l-2 border-malachite pl-3">
              <dd className="num text-[1.9rem] leading-none font-semibold text-ink sm:text-[2.2rem]">
                <CountUp to={n} run={seen} />
                {label === "automated tests" ? "+" : ""}
              </dd>
              <dt className="mt-1.5 text-caption text-ink-3">{label}</dt>
            </div>
          ))}
      </dl>

      <div ref={wrap} className="panel p-3 sm:p-5">
        <p className="mb-2 flex items-center gap-2 px-1 text-caption text-ink-3">
          <svg aria-hidden viewBox="0 0 20 20" className="size-4 text-malachite" style={touched ? undefined : { animation: "strata-tap 2.4s ease-in-out infinite" }}>
            <path
              d="M7.5 9.5V3.8a1.3 1.3 0 0 1 2.6 0v5l.2-1.2a1.3 1.3 0 0 1 2.5.4v1l.3-.6a1.3 1.3 0 0 1 2.4.7v4.4c0 2.6-2 4.5-4.6 4.5h-1c-1.6 0-3-.8-3.8-2.1L3.8 12a1.3 1.3 0 0 1 2.1-1.5z"
              fill="#e2efe9"
              stroke="currentColor"
              strokeWidth={1.4}
              strokeLinejoin="round"
            />
          </svg>
          Tap a box to see what it does.
        </p>
        <svg viewBox={`0 0 ${L.w} ${L.h}`} className="mx-auto block w-full" style={{ maxWidth: L.w }} role="group" aria-label="How Strata is built">
          <defs>
            <marker id="wire-head" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto-start-reverse">
              <path d="M0 0L8 4L0 8z" fill="#1e2630" fillOpacity={0.55} />
            </marker>
            <marker id="wire-head-on" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={7} markerHeight={7} orient="auto-start-reverse">
              <path d="M0 0L8 4L0 8z" fill="#1d6b56" />
            </marker>
          </defs>

          {EDGES.map((e) => {
            const g = geometry(e, L);
            const on = linked(e);
            const summary = e.kind === "summary";
            const color = summary ? "#9a6a12" : on ? "#1d6b56" : "#1e2630";
            return (
              <g key={`${e.from}-${e.to}`} className="transition-opacity duration-300" style={{ opacity: on ? 1 : 0.55 }}>
                <path
                  d={g.d}
                  fill="none"
                  stroke={color}
                  strokeOpacity={on ? 0.55 : 0.3}
                  strokeWidth={on ? 2 : 1.4}
                  strokeDasharray={summary ? "5 4" : undefined}
                  markerEnd={`url(#${on ? "wire-head-on" : "wire-head"})`}
                />
                {!summary ? (
                  <path
                    d={g.d}
                    fill="none"
                    stroke={color}
                    strokeWidth={on ? 3 : 2.2}
                    strokeLinecap="round"
                    strokeDasharray="0.5 23.5"
                    style={{ animation: `strata-flow ${on ? 0.8 : 1.6}s linear infinite` }}
                  />
                ) : (
                  <g transform={`translate(${g.mid[0]} ${g.mid[1]})`}>
                    <rect x={-44} y={-11} width={88} height={22} rx={4} fill="#f6eedb" stroke="#c08419" strokeOpacity={0.6} />
                    <text textAnchor="middle" y={4.5} style={{ fontSize: 12.5 }} className="fill-loess">
                      summaries only
                    </text>
                  </g>
                )}
              </g>
            );
          })}

          {(Object.keys(NODES) as Id[]).map((id, i) => {
            const [cx, cy] = L.at[id];
            const [w, h] = L.box;
            const on = sel === id;
            const n = NODES[id];
            return (
              <g
                key={id}
                role="button"
                tabIndex={0}
                aria-pressed={on}
                aria-label={`${n.title}, ${n.sub}`}
                className="cursor-pointer outline-none [&:focus-visible>rect]:stroke-malachite"
                onClick={() => setSel(id)}
                onMouseEnter={() => setSel(id)}
                onFocus={() => setSel(id)}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSel(id))}
                style={{
                  transformBox: "fill-box",
                  transformOrigin: "center",
                  transform: on ? "translateY(-2px)" : undefined,
                  transition: "transform 200ms",
                  animation: seen ? `strata-pop 320ms cubic-bezier(.3,1.5,.5,1) ${i * 70}ms both` : undefined,
                }}
              >
                {!touched && !on ? (
                  <rect
                    x={cx - w / 2 - 4}
                    y={cy - h / 2 - 4}
                    width={w + 8}
                    height={h + 8}
                    rx={11}
                    fill="none"
                    stroke="#1d6b56"
                    strokeWidth={2}
                    strokeOpacity={0}
                    style={{ animation: `strata-beckon 2.6s ease-in-out ${1.2 + i * 0.33}s infinite` }}
                  />
                ) : null}
                <rect
                  x={cx - w / 2}
                  y={cy - h / 2 + 3}
                  width={w}
                  height={h}
                  rx={8}
                  fill="#1e2630"
                  fillOpacity={on ? 0.22 : 0.08}
                />
                <rect
                  x={cx - w / 2}
                  y={cy - h / 2}
                  width={w}
                  height={h}
                  rx={8}
                  fill={on ? "#e2efe9" : id === "assistant" ? "#fbf6ea" : "#fff"}
                  stroke={on ? "#1d6b56" : id === "assistant" ? "#c08419" : "#b9c1bf"}
                  strokeWidth={on ? 2 : 1}
                  className="transition-[fill,stroke] duration-200"
                />
                <text x={cx} y={cy - 2} textAnchor="middle" style={{ fontSize: 16, fontWeight: 600 }} className="fill-ink">
                  {n.title}
                </text>
                <text x={cx} y={cy + 15} textAnchor="middle" style={{ fontSize: 12.5 }} className="num fill-ink-3">
                  {n.sub}
                </text>
                {/* A corner badge: plus to open, filled when this box is the one shown below. */}
                <g transform={`translate(${cx + w / 2} ${cy - h / 2})`}>
                  <circle r={8} fill={on ? "#1d6b56" : "#fff"} stroke={on ? "#1d6b56" : "#8a949c"} strokeWidth={1.2} className="transition-[fill,stroke] duration-200" />
                  {on ? (
                    <path d="M-3.4 -1.4 L0 2 L3.4 -1.4" fill="none" stroke="#fff" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
                  ) : (
                    <path d="M-3.6 0 H3.6 M0 -3.6 V3.6" stroke="#4f5963" strokeWidth={1.7} strokeLinecap="round" />
                  )}
                </g>
              </g>
            );
          })}
        </svg>

        <div className="mt-3 min-h-[5.5rem] rounded-[6px] bg-wash/70 px-4 py-3 sm:px-5" aria-live="polite">
          <p key={sel} className="text-[1.08rem] leading-[1.55] text-ink" style={{ animation: "strata-label 300ms ease-out both" }}>
            <span className="font-semibold">{NODES[sel].title}.</span> {NODES[sel].detail}
          </p>
        </div>
      </div>
    </div>
  );
}
