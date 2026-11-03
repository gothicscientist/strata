"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";

/**
 * A technical word with its plain meaning one hover (or tap) away. The word stays in the text,
 * so specialists read it as normal, and everyone else can ask what it means.
 */
export function Term({ k, children }: { k: GlossaryKey; children?: React.ReactNode }) {
  const g = GLOSSARY[k];
  const [open, setOpen] = useState(false);
  const id = useId();
  const ref = useRef<HTMLSpanElement | null>(null);
  const bubble = useRef<HTMLSpanElement | null>(null);
  const [dx, setDx] = useState(0);
  // Keep the bubble on screen near the edges of a phone.
  useLayoutEffect(() => {
    if (!open || !bubble.current || !ref.current) return setDx(0);
    const t = ref.current.getBoundingClientRect();
    const w = bubble.current.offsetWidth;
    const left = t.left + t.width / 2 - w / 2;
    const max = document.documentElement.clientWidth - 12;
    setDx(left < 12 ? 12 - left : left + w > max ? max - (left + w) : 0);
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  return (
    <span
      ref={ref}
      className="relative inline-block"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="term cursor-help text-inherit"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        {children ?? g.term}
      </button>
      {open ? (
        <span
          id={id}
          ref={bubble}
          role="tooltip"
          className="pop absolute bottom-[calc(100%+0.5rem)] left-1/2 z-30 w-[17rem] max-w-[calc(100vw-24px)] rounded-[var(--radius-panel)] bg-basalt px-3.5 py-2.5 text-left text-[0.95rem] leading-[1.45] font-normal text-[#e3e8ec] shadow-[0_6px_0_rgba(30,38,48,.18)]"
          style={{ transformOrigin: "50% 100%", translate: `calc(-50% + ${dx}px) 0` }}
        >
          <span className="mb-0.5 block font-semibold text-white">{g.term}</span>
          {g.plain}
          <span aria-hidden style={{ marginLeft: -6 - dx }} className="absolute top-full left-1/2 border-x-[6px] border-t-[6px] border-x-transparent border-t-basalt" />
        </span>
      ) : null}
    </span>
  );
}
