"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Term } from "./Term";
import { useSeen } from "@/lib/useSeen";

/* ------------------------------------------------------------------------------------------
 * The four steps of an analysis, each shown as a small moving picture with one plain sentence.
 * A switch swaps the plain sentence for what the code actually does. The pictures use made-up
 * numbers; the text under the hood describes the real pipeline.
 * ---------------------------------------------------------------------------------------- */

const STEP_MS = 6500;

/* ---- Scene 1: a raw file is lined up with the reference panel ---------------------------- */

const ROWS: Array<{ id: string; you: string; panel: string; out: "kept" | "flipped" | "dropped" }> = [
  { id: "rs3094315", you: "AG", panel: "A/G", out: "kept" },
  { id: "rs12562034", you: "GG", panel: "G/A", out: "kept" },
  { id: "rs2905036", you: "TC", panel: "A/G", out: "flipped" },
  { id: "rs1110052", you: "AT", panel: "A/T", out: "dropped" },
  { id: "rs3748597", you: "CC", panel: "C/T", out: "kept" },
];

const OUT = {
  kept: { label: "kept", short: "kept", cls: "bg-malachite-soft text-malachite" },
  flipped: { label: "strand flipped", short: "flipped", cls: "bg-loess-soft text-loess" },
  dropped: { label: "ambiguous, dropped", short: "dropped", cls: "bg-wash text-ink-3 line-through" },
} as const;

function UploadScene() {
  return (
    <div className="flex h-full flex-col justify-center gap-1.5 px-1 sm:px-4">
      <div className="num grid grid-cols-[6.2rem_2.6rem_3rem_1fr] gap-x-3 px-2 text-[0.8rem] text-ink-3 sm:grid-cols-[7rem_3rem_3.5rem_1fr]">
        <span>SNP</span>
        <span>You</span>
        <span>Panel</span>
        <span />
      </div>
      {ROWS.map((r, i) => (
        <div
          key={r.id}
          className="num grid grid-cols-[6.2rem_2.6rem_3rem_1fr] items-center gap-x-3 rounded-[6px] bg-wash/70 px-2 py-1 text-[0.86rem] sm:grid-cols-[7rem_3rem_3.5rem_1fr] sm:text-[0.95rem]"
          style={{ animation: `strata-label 380ms ease-out ${i * 160}ms both` }}
        >
          <span className="truncate text-ink-2">{r.id}</span>
          <span className="font-semibold text-ink">{r.you}</span>
          <span className="text-ink-2">{r.panel}</span>
          <span
            className={`justify-self-start rounded-[3px] px-1.5 text-[0.78rem] whitespace-nowrap sm:text-[0.82rem] ${OUT[r.out].cls}`}
            style={{ animation: `strata-pop 260ms cubic-bezier(.3,1.6,.5,1) ${900 + i * 260}ms both` }}
          >
            <span className="sm:hidden">{OUT[r.out].short}</span>
            <span className="hidden sm:inline">{OUT[r.out].label}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

/* ---- Scene 2: the sample drops into the PCA ----------------------------------------------- */

function rng(seed: number) {
  let s = seed;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

const CLUSTERS = [
  { name: "Steppe herders", x: 92, y: 58, c: "#2c5c94", lx: 92, ly: 22 },
  { name: "Iranian farmers", x: 318, y: 66, c: "#a13f5e", lx: 318, ly: 26 },
  { name: "South Asians today", x: 270, y: 168, c: "#4a9a68", lx: 318, ly: 222 },
  { name: "Anatolian farmers", x: 82, y: 172, c: "#c08419", lx: 82, ly: 222 },
];

const POINTS = (() => {
  const r = rng(7);
  const g = () => (r() + r() + r() - 1.5) * 2;
  return CLUSTERS.flatMap((c, ci) =>
    Array.from({ length: 20 }, () => ({ x: c.x + g() * 22, y: c.y + g() * 14, c: c.c, ci })),
  );
})();

const YOU = { x: 236, y: 140 };

function PlaceScene() {
  const near = CLUSTERS[2]!;
  return (
    <svg viewBox="0 0 400 240" className="h-full w-full" role="img" aria-label="Illustration: a sample lands among reference clusters in a PCA">
      <line x1={20} x2={380} y1={120} y2={120} stroke="#1e2630" strokeOpacity={0.12} />
      <line x1={200} x2={200} y1={10} y2={230} stroke="#1e2630" strokeOpacity={0.12} />
      {POINTS.map((p, i) => (
        <circle
          key={i}
          cx={p.x}
          cy={p.y}
          r={3.2}
          fill={p.c}
          fillOpacity={0.55}
          style={{ transformBox: "fill-box", transformOrigin: "center", animation: `strata-pop 300ms ease-out ${p.ci * 120 + (i % 20) * 14}ms both` }}
        />
      ))}
      {CLUSTERS.map((c, i) => (
        <text
          key={c.name}
          x={c.lx}
          y={c.ly}
          textAnchor="middle"
          className="fill-ink-2"
          style={{ fontSize: 13, animation: `strata-label 400ms ease-out ${300 + i * 120}ms both` }}
        >
          {c.name}
        </text>
      ))}
      <line
        x1={YOU.x}
        y1={YOU.y}
        x2={near.x}
        y2={near.y}
        stroke="#1d6b56"
        strokeWidth={1.5}
        strokeDasharray="1"
        pathLength={1}
        style={{ animation: "strata-trace 500ms ease-out 1700ms both" }}
      />
      <g style={{ animation: "strata-drop 700ms cubic-bezier(.3,.7,.4,1.25) 900ms both" }}>
        <circle
          cx={YOU.x}
          cy={YOU.y}
          r={7}
          fill="none"
          stroke="#1d6b56"
          strokeWidth={2}
          style={{ transformBox: "fill-box", transformOrigin: "center", animation: "strata-ring 1200ms ease-out 1550ms both" }}
        />
        <circle cx={YOU.x} cy={YOU.y} r={7} fill="#1d6b56" stroke="#fff" strokeWidth={2} />
        <text x={YOU.x - 12} y={YOU.y + 4} textAnchor="end" style={{ fontSize: 14, fontWeight: 600 }} className="fill-malachite">
          You
        </text>
      </g>
    </svg>
  );
}

/* ---- Scene 3: a mixture of sources fills up ------------------------------------------------ */

const MIX = [
  { name: "Iranian farmers", w: 52, c: "#a13f5e" },
  { name: "Steppe herders", w: 30, c: "#2c5c94" },
  { name: "Anatolian farmers", w: 18, c: "#c08419" },
];

function FitScene() {
  return (
    <div className="flex h-full flex-col justify-center gap-3 px-1 sm:px-4">
      {MIX.map((m, i) => (
        <div key={m.name} className="grid grid-cols-[8.5rem_minmax(0,1fr)_2.6rem] items-center gap-x-3 sm:grid-cols-[10rem_minmax(0,1fr)_3rem]">
          <span className="truncate text-[0.98rem] text-ink-2">{m.name}</span>
          <span className="h-3 rounded-full bg-wash">
            <span
              className="block h-full origin-left rounded-full"
              style={{ width: `${m.w}%`, background: m.c, animation: `strata-grow 700ms cubic-bezier(.2,.8,.2,1) ${300 + i * 250}ms both` }}
            />
          </span>
          <span className="num text-right font-semibold text-ink" style={{ animation: `strata-label 300ms ease-out ${800 + i * 250}ms both` }}>
            {m.w}%
          </span>
        </div>
      ))}
      <div className="mt-3 flex h-7 overflow-hidden rounded-[6px] border border-rule">
        {MIX.map((m, i) => (
          <span
            key={m.name}
            className="h-full origin-left"
            style={{ width: `${m.w}%`, background: m.c, animation: `strata-grow 450ms ease-out ${1500 + i * 300}ms both` }}
          />
        ))}
      </div>
      <p className="num text-[0.9rem] text-ink-3" style={{ animation: "strata-label 400ms ease-out 2500ms both" }}>
        Weights add to 100%, none below zero.
      </p>
    </div>
  );
}

/* ---- Scene 4: the formal test lands on a verdict ------------------------------------------ */

/** Position of a p-value on a log axis from 1e-4 (left) to 1 (right), as a percentage. */
const pAt = (p: number) => ((Math.log10(p) + 4) / 4) * 100;

function TestScene() {
  const p = 0.3;
  return (
    <div className="flex h-full flex-col justify-center px-1 sm:px-4">
      <div className="relative mt-10 h-9">
        <div className="absolute inset-0 flex overflow-hidden rounded-[6px] text-[0.8rem] sm:text-[0.86rem]">
          <span className="flex items-center justify-center bg-[#f3dcd8] text-[#8a2a20]" style={{ width: `${pAt(0.01)}%` }}>
            rejected
          </span>
          <span className="flex items-center justify-center bg-loess-soft text-loess" style={{ width: `${pAt(0.05) - pAt(0.01)}%` }}>
            <span className="hidden sm:inline">marginal</span>
          </span>
          <span className="flex flex-1 items-center bg-malachite-soft pl-3 text-malachite">plausible</span>
        </div>
        <span
          className="absolute -top-8 flex -translate-x-1/2 flex-col items-center"
          style={{ "--x": `${pAt(p)}%`, animation: "strata-slide 1300ms cubic-bezier(.5,0,.2,1.15) 300ms both" } as React.CSSProperties}
        >
          <span className="num rounded-[3px] bg-ink px-1.5 text-[0.82rem] whitespace-nowrap text-white">p = {p.toFixed(2)}</span>
          <span className="h-9 w-0.5 bg-ink" />
        </span>
      </div>
      <div className="num relative mt-1 h-4 text-[0.78rem] text-ink-3">
        <span className="absolute left-0">0.0001</span>
        <span className="absolute -translate-x-1/2" style={{ left: `${pAt(0.01)}%` }}>
          0.01
        </span>
        <span className="absolute right-0">1</span>
      </div>
      <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2">
        <span
          className="rounded-[6px] border-2 border-malachite px-3 py-1 text-[1.25rem] font-semibold text-malachite"
          style={{ animation: "strata-stamp 380ms cubic-bezier(.3,1.5,.5,1) 1700ms both" }}
        >
          Not rejected
        </span>
        <span className="num text-[0.9rem] text-ink-3" style={{ animation: "strata-label 400ms ease-out 2000ms both" }}>
          χ² 6.1 on 5 degrees of freedom
        </span>
      </div>
    </div>
  );
}

/* ---- Steps --------------------------------------------------------------------------------- */

interface Step {
  title: string;
  plain: string;
  hood: React.ReactNode;
  href: string;
  action: string;
  Scene: () => React.ReactElement;
}

const STEPS: Step[] = [
  {
    title: "Upload",
    plain: "Drop in the raw file from 23andMe or AncestryDNA, a VCF, or G25 coordinates.",
    hood: (
      <>
        Each format is parsed and lined up with the 417,935-<Term k="snp" /> reference panel. Strand flips are
        corrected; A/T and C/G sites are dropped because their strand cannot be told. The file is stored encrypted
        (AES-256-GCM) under its own key, and deleting that key makes every copy unreadable.
      </>
    ),
    href: "/upload/",
    action: "Upload a file",
    Scene: UploadScene,
  },
  {
    title: "Place",
    plain: "See which ancient and present-day people your DNA sits closest to.",
    hood: (
      <>
        A <Term k="pca" /> fitted on 2,729 present-day people. Ancient samples, and yours, are projected using only
        the SNPs each one actually has, so gaps in old DNA do not pull a sample toward the middle. Reference scores
        are out-of-fold, so they sit on the same scale as yours.
      </>
    ),
    href: "/analyses/new/?method=pca_project",
    action: "Project a sample",
    Scene: PlaceScene,
  },
  {
    title: "Fit",
    plain: "Find the mix of source populations that best rebuilds your position.",
    hood: (
      <>
        Least squares with the weights held non-negative and summing to one, solved exactly by an active-set method.
        Quick and useful for choosing candidates, but exploratory: a close fit is not evidence of{" "}
        <Term k="admixture">admixture</Term>.
      </>
    ),
    href: "/analyses/new/?method=admixture_fit",
    action: "Fit sources",
    Scene: FitScene,
  },
  {
    title: "Test",
    plain: "Ask whether that mix survives a formal test, and get a clear verdict.",
    hood: (
      <>
        <Term k="qpadm" /> (ADMIXTOOLS 2) checks the model against <Term k="f4">f4-statistics</Term> with a set of
        outgroups. Error bars come from a <Term k="jackknife">block jackknife</Term> over 5 cM stretches of genome.
        Below p = 0.01 the model is rejected; above 0.05 it is plausible, which is not the same as proven.
      </>
    ),
    href: "/analyses/new/?method=qpadm",
    action: "Set up qpAdm",
    Scene: TestScene,
  },
];

export function Explainer() {
  const [ref, visible] = useSeen<HTMLDivElement>(0.3, true);
  const [step, setStep] = useState(0);
  const [auto, setAuto] = useState(true);
  const [hood, setHood] = useState(false);
  const [plays, setPlays] = useState(0);

  useEffect(() => {
    if (!auto || !visible) return;
    const t = window.setTimeout(() => setStep((s) => (s + 1) % STEPS.length), STEP_MS);
    return () => window.clearTimeout(t);
  }, [auto, visible, step]);

  const pick = (i: number) => {
    setAuto(false);
    setStep(i);
    setPlays((p) => p + 1);
  };
  const onKey = (e: React.KeyboardEvent) => {
    const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const next = (step + d + STEPS.length) % STEPS.length;
    pick(next);
    document.getElementById(`step-tab-${next}`)?.focus();
  };

  const s = STEPS[step]!;
  const Scene = s.Scene;

  return (
    <div ref={ref} className="grid gap-5 lg:grid-cols-[17rem_minmax(0,1fr)] lg:gap-8">
      <div role="tablist" aria-label="Steps" aria-orientation="vertical" onKeyDown={onKey} className="grid grid-cols-4 gap-1.5 lg:grid-cols-1 lg:gap-1">
        {STEPS.map((t, i) => {
          const on = i === step;
          return (
            <button
              key={t.title}
              id={`step-tab-${i}`}
              role="tab"
              type="button"
              aria-selected={on}
              aria-controls="step-panel"
              tabIndex={on ? 0 : -1}
              onClick={() => pick(i)}
              className={`group relative overflow-hidden rounded-[var(--radius-panel)] border px-1 py-2 text-center lg:text-left transition-[background-color,border-color,transform] duration-200 lg:px-4 lg:py-3 ${
                on ? "border-ink bg-panel" : "border-transparent hover:-translate-y-px hover:bg-panel/70"
              }`}
            >
              <span className="flex flex-col items-center gap-1 lg:flex-row lg:gap-2.5">
                <span
                  key={on ? `on-${plays}` : "off"}
                  className={`num flex size-7 shrink-0 items-center justify-center rounded-full text-[0.9rem] font-semibold transition-colors ${
                    on ? "pop bg-malachite text-white" : "bg-ink/80 text-white group-hover:bg-ink"
                  }`}
                >
                  {i + 1}
                </span>
                <span className="text-[0.98rem] font-semibold text-ink lg:text-h3">{t.title}</span>
              </span>
              <span className={`mt-1 hidden text-small leading-[1.45] text-ink-2 lg:block ${on ? "" : "opacity-70"}`}>{t.plain}</span>
              {on && auto && visible ? (
                <span
                  key={`bar-${step}`}
                  aria-hidden
                  className="absolute right-0 bottom-0 left-0 h-[3px] origin-left bg-malachite"
                  style={{ animation: `strata-grow ${STEP_MS}ms linear both` }}
                />
              ) : null}
            </button>
          );
        })}
      </div>

      <div id="step-panel" role="tabpanel" aria-labelledby={`step-tab-${step}`} className="panel flex min-w-0 flex-col">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule-soft px-4 py-2.5 sm:px-5">
          <div className="inline-flex rounded-[6px] bg-wash p-0.5 text-[0.95rem]" role="group" aria-label="Explanation level">
            {[
              [false, "Plain words"],
              [true, "Under the hood"],
            ].map(([v, label]) => (
              <button
                key={String(label)}
                type="button"
                aria-pressed={hood === v}
                onClick={() => {
                  setHood(v as boolean);
                  setAuto(false);
                }}
                className={`rounded-[5px] px-3 py-1 font-medium transition-[background-color,color,box-shadow] duration-200 ${
                  hood === v ? "bg-panel text-ink shadow-[0_1px_0_rgba(30,38,48,.18)]" : "text-ink-3 hover:text-ink"
                }`}
              >
                {label as string}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => pick(step)} className="linkish text-[0.95rem] text-ink-3 hover:text-malachite">
            Play again
          </button>
        </div>

        <div key={`${step}-${plays}`} className="h-[15.5rem] overflow-hidden px-3 pt-4 sm:h-[16.5rem] sm:px-5 lg:my-auto" aria-hidden>
          <Scene />
        </div>

        <div className="px-4 pt-2 pb-5 sm:px-6">
          <p key={`${step}-${hood}`} className={`${hood ? "" : "lg:hidden"} text-[1.15rem] leading-[1.6] text-ink`} style={{ animation: "strata-label 360ms ease-out both" }}>
            {hood ? s.hood : s.plain}
          </p>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <Link href={s.href} className="text-small font-semibold">
              {s.action}
            </Link>
            <span className="text-caption text-ink-3">Illustration, not real data.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
