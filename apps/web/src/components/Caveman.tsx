"use client";

import { useEffect, useId, useState } from "react";

/* ------------------------------------------------------------------------------------------
 * The site's small Palaeolithic digger, drawn like a coloured pencil sketch: ink outlines over
 * fills printed a hair off register, with a slow "boil" on the lines. Every movement is CSS
 * (see the Caveman section of globals.css) and stops under prefers-reduced-motion.
 *
 *   dig      chips at the ground with a hafted flint pick
 *   idle     breathes and blinks
 *   walk     strolls (the footer moves him; this only swings the legs)
 *   puzzled  scratches his head
 *   cheer    both arms up, bouncing
 * ---------------------------------------------------------------------------------------- */

export type CavemanPose = "dig" | "idle" | "walk" | "puzzled" | "cheer";

const INK = "#1e2630";
const SKIN = "#e8b98d";
const HAIR = "#4a3424";
const HAIR_LIGHT = "#7a5a42";
const FUR = "#a46a3a";
const FUR_DARK = "#7d4b27";
const FLINT = "#7f8b98";
const FLINT_LIGHT = "#c3ccd4";
const WOOD = "#8a5418";
const MALACHITE = "#1d6b56";

/** Fill nudged off its outline, the way a marker colours a pencil sketch. */
const OFF = "translate(0.9 0.7)";

function Shape({ d, fill, sw = 1.4 }: { d: string; fill: string; sw?: number }) {
  return (
    <>
      <path d={d} fill={fill} transform={OFF} />
      <path d={d} fill="none" stroke={INK} strokeWidth={sw} strokeLinejoin="round" strokeLinecap="round" />
    </>
  );
}

/** A limb: a thick ink stroke with a thinner skin stroke inside it. */
function Limb({ d }: { d: string }) {
  return (
    <>
      <path d={d} fill="none" stroke={INK} strokeWidth={6.2} strokeLinecap="round" />
      <path d={d} fill="none" stroke={SKIN} strokeWidth={3.9} strokeLinecap="round" />
    </>
  );
}

function useReducedMotion(): boolean {
  // Starts true so the static export never ships an animated filter to someone who opted out.
  const [reduced, setReduced] = useState(true);
  useEffect(() => {
    const m = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!m) return setReduced(false);
    const update = () => setReduced(m.matches);
    update();
    m.addEventListener("change", update);
    return () => m.removeEventListener("change", update);
  }, []);
  return reduced;
}

export interface CavemanProps {
  pose?: CavemanPose;
  /** Height in CSS pixels; the width follows (0.8 of it). */
  size?: number;
  className?: string;
  /** When given, he becomes a button that hops when pressed. */
  onPoke?: () => void;
  /** Accessible name when he is a button. */
  label?: string;
  style?: React.CSSProperties;
}

export function Caveman({ pose = "idle", size = 72, className, onPoke, label = "Caveman", style }: CavemanProps) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const reduced = useReducedMotion();
  const [hops, setHops] = useState(0);
  const rough = `cm-rough-${uid}`;

  const art = (
    <svg
      width={Math.round(size * 0.8)}
      height={size}
      viewBox="0 0 64 80"
      className="cm overflow-visible"
      data-pose={pose}
      aria-hidden
      focusable="false"
    >
      <defs>
        <filter id={rough} filterUnits="userSpaceOnUse" x={-40} y={-30} width={150} height={130}>
          <feTurbulence type="fractalNoise" baseFrequency={0.07} numOctaves={2} seed={3} result="n">
            {reduced ? null : <animate attributeName="seed" values="3;8;13" dur="0.8s" calcMode="discrete" repeatCount="indefinite" />}
          </feTurbulence>
          <feDisplacementMap in="SourceGraphic" in2="n" scale={1.5} xChannelSelector="R" yChannelSelector="G" />
        </filter>
      </defs>

      <ellipse className="cm-shadow" cx={32} cy={77} rx={15} ry={2.3} fill={INK} fillOpacity={0.14} />

      <g filter={`url(#${rough})`}>
        <g key={hops} className={`cm-fig${hops ? " cm-hop" : ""}`}>
          {/* Legs, each with a hide wrap on the foot */}
          <g className="cm-leg-l">
            <Limb d="M27 56 L25.6 70.5" />
            <Shape d="M20 73.4 q0 -3.4 5.5 -3.2 q4.5 .2 4.2 3.2 q-.2 1.8 -4.8 1.8 q-4.9 0 -4.9 -1.8z" fill={FUR} sw={1.3} />
          </g>
          <g className="cm-leg-r">
            <Limb d="M37 56 L38.4 70.5" />
            <Shape d="M44 73.4 q0 -3.4 -5.5 -3.2 q-4.5 .2 -4.2 3.2 q.2 1.8 4.8 1.8 q4.9 0 4.9 -1.8z" fill={FUR} sw={1.3} />
          </g>

          <g className="cm-torso">
            {/* Fur tunic with a ragged hem */}
            <Shape
              d="M21 36.5 C25 33 39 33 43 36.5 C45.5 42 46 50 46.5 58.5 L43.5 56.6 L41 59.6 L38.2 56.8 L35.4 60 L32.6 57 L29.8 60 L27 56.8 L24.2 59.6 L21.4 56.8 L17.8 58.6 C18.2 50 18.6 42 21 36.5 Z"
              fill={FUR}
            />
            <g fill={FUR_DARK}>
              <ellipse cx={25.6} cy={45} rx={1.7} ry={1.3} />
              <ellipse cx={38.4} cy={49} rx={1.4} ry={1.1} />
              <ellipse cx={31} cy={52.6} rx={1.5} ry={1.1} />
              <ellipse cx={39.6} cy={41.6} rx={1.1} ry={0.9} />
            </g>
            <path d="M42.2 44.4 l2 -2.4 M42.6 48.4 l2 -2.4 M43 52.4 l2 -2.4" stroke={FUR_DARK} strokeWidth={0.9} strokeLinecap="round" />

            {/* Pick arm: a flint point lashed to a stick */}
            <g className="cm-tool-arm">
              <path d="M19.6 46.4 L12.2 66" stroke={INK} strokeWidth={3.4} strokeLinecap="round" />
              <path d="M19.6 46.4 L12.2 66" stroke={WOOD} strokeWidth={1.7} strokeLinecap="round" />
              <Shape d="M9.4 63.5 C11 62 14.2 62.6 15.2 64.6 C14.4 67.6 11.6 70.8 8.6 72.6 C8 69.4 8.2 65.4 9.4 63.5 Z" fill={FLINT} sw={1.3} />
              <path d="M10.6 65.6 l2 1.5 M10.1 68.4 l1.5 .9" stroke={FLINT_LIGHT} strokeWidth={0.9} strokeLinecap="round" />
              <path d="M11.2 62.9 l2.8 2.3 M12.6 62.3 l2.4 2.4" stroke="#d8b47a" strokeWidth={1} strokeLinecap="round" />
              <Limb d="M21.5 38.5 Q17.6 45 17.1 51.4" />
              <circle cx={17.1} cy={53} r={2.9} fill={SKIN} stroke={INK} strokeWidth={1.3} />
            </g>

            <g className="cm-free-arm">
              <Limb d="M42.5 38.5 Q47.4 45 47.4 51.4" />
              <circle cx={47.4} cy={53} r={2.8} fill={SKIN} stroke={INK} strokeWidth={1.3} />
            </g>

            <g className="cm-head">
              {/* Ears, face */}
              <ellipse cx={20.8} cy={23} rx={2} ry={2.8} fill={SKIN} stroke={INK} strokeWidth={1.3} />
              <ellipse cx={43.2} cy={23} rx={2} ry={2.8} fill={SKIN} stroke={INK} strokeWidth={1.3} />
              <Shape d="M32 10.1 a11.4 11.4 0 1 1 -0.01 0 z" fill={SKIN} sw={1.5} />
              <ellipse cx={25.3} cy={26} rx={1.9} ry={1.1} fill="#d9826e" fillOpacity={0.5} />
              <ellipse cx={38.7} cy={26} rx={1.9} ry={1.1} fill="#d9826e" fillOpacity={0.5} />

              {/* Shaggy hair with a fringe */}
              <Shape
                d="M19.5 24 C18 17 19.5 11 24 9.5 C25 7 28.5 6.5 30.5 8 C32 6 36 6.2 37.5 8.4 C40.5 7.8 44 10.5 44 14 C46 16.5 45.6 21 44.4 24 C43.6 21 42.6 18 40.8 15.8 C39.6 17 37.8 17.2 36.8 15.8 C35.2 17.2 32.8 17.2 31.6 15.8 C30.2 17.2 27.8 17 26.8 15.6 C25.2 16.8 23.4 16.6 22.8 15.6 C21.2 17.4 20.2 20.6 19.5 24 Z"
                fill={HAIR}
              />
              <path d="M25.6 11.6 q2 -1.5 4 0 M33 10.4 q2 -1.2 4 .4 M39.6 12.6 q1.4 .2 2.2 1.6" stroke={HAIR_LIGHT} strokeWidth={0.9} fill="none" strokeLinecap="round" />

              {/* Beard, open around the mouth */}
              <Shape
                d="M21.2 24 C21.4 31.5 25.5 36.6 32 36.8 C38.5 36.6 42.6 31.5 42.8 24 C41.4 26.6 39.8 28.2 38 28.6 C36.4 30.8 27.6 30.8 26 28.6 C24.2 28.2 22.6 26.6 21.2 24 Z"
                fill={HAIR}
              />
              <path d="M27 32.8 l.8 1.6 M32 33.6 v1.8 M37 32.8 l-.8 1.6" stroke={HAIR_LIGHT} strokeWidth={0.9} strokeLinecap="round" />

              {/* Heavy brow, eyes, a round nose, a smile */}
              <path d="M25.2 19.6 Q28.2 18 30.8 19.6 M33.2 19.6 Q35.8 18 38.8 19.6" stroke={HAIR} strokeWidth={2.1} fill="none" strokeLinecap="round" />
              <g className="cm-look">
                <g className="cm-eyes">
                  <ellipse cx={28.2} cy={22.4} rx={1.55} ry={1.95} fill={INK} />
                  <ellipse cx={35.8} cy={22.4} rx={1.55} ry={1.95} fill={INK} />
                  <circle cx={28.7} cy={21.7} r={0.5} fill="#fff" />
                  <circle cx={36.3} cy={21.7} r={0.5} fill="#fff" />
                </g>
              </g>
              <path d="M31.4 23.4 C30 25.6 30.8 26.6 32.2 26.4 C33.4 26.3 33.6 25.4 32.8 24.8" stroke={INK} strokeWidth={1.15} fill="none" strokeLinecap="round" />
              <path d="M29.4 28.3 Q32 30.1 34.6 28.3" stroke={INK} strokeWidth={1.2} fill="none" strokeLinecap="round" />
            </g>

            {/* A cord with two malachite beads and a tooth */}
            <path d="M25.6 35.8 Q32 40.6 38.4 35.8" stroke={INK} strokeWidth={0.9} fill="none" />
            <circle cx={28.6} cy={38} r={1.3} fill={MALACHITE} stroke={INK} strokeWidth={0.6} />
            <circle cx={35.4} cy={38} r={1.3} fill={MALACHITE} stroke={INK} strokeWidth={0.6} />
            <path d="M31 38.6 l1 3.3 l1 -3.3 z" fill="#f4efe2" stroke={INK} strokeWidth={0.7} strokeLinejoin="round" />
          </g>
        </g>

        {/* Chips thrown up when the pick lands */}
        <g fill="#cdae66" stroke={INK} strokeWidth={0.5}>
          <circle className="cm-dust" cx={8} cy={73} r={1.3} style={{ "--dx": "-4px", "--dy": "-5px" } as React.CSSProperties} />
          <circle className="cm-dust" cx={10.5} cy={73.6} r={0.9} style={{ "--dx": "2px", "--dy": "-6px" } as React.CSSProperties} />
          <circle className="cm-dust" cx={6} cy={74} r={0.8} style={{ "--dx": "-6px", "--dy": "-2px" } as React.CSSProperties} />
        </g>

        {pose === "puzzled" ? (
          <text className="cm-q" x={50} y={10} style={{ fontSize: 13, fontWeight: 600 }} fill={MALACHITE}>
            ?
          </text>
        ) : null}
      </g>
    </svg>
  );

  if (!onPoke)
    return (
      <span className={`inline-block leading-none ${className ?? ""}`} style={style}>
        {art}
      </span>
    );
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`cm-host cm-button ${className ?? ""}`}
      style={style}
      onClick={() => {
        setHops((h) => h + 1);
        onPoke();
      }}
    >
      {art}
    </button>
  );
}
