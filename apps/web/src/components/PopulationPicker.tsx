"use client";

import { useEffect, useId, useState } from "react";
import { api } from "@/lib/api";
import { bpRange } from "@/lib/format";
import type { PopulationSummary } from "@/lib/types";

export interface Picked {
  id: string;
  name: string;
}

/**
 * Searchable multi-select over the reference library. Keyboard: type to search, arrow keys to
 * move, Enter to add; selected entries are listed in order with a remove control.
 */
export function PopulationPicker({
  label,
  hint,
  value,
  onChange,
  max,
  exclude = [],
  space,
}: {
  label: string;
  hint?: string;
  value: Picked[];
  onChange: (v: Picked[]) => void;
  max?: number;
  exclude?: string[];
  space?: string;
}) {
  const id = useId();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<PopulationSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!q.trim()) {
      setHits([]);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      api
        .populations({ q, page_size: 12, space }, ctrl.signal)
        .then((p) => {
          setHits(p.items);
          setActive(0);
          setError(null);
        })
        .catch((e: unknown) => {
          if (!ctrl.signal.aborted) setError(e instanceof Error ? e.message : String(e));
        });
    }, 200);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q, space]);

  const taken = new Set([...value.map((v) => v.id), ...exclude]);
  const options = hits.filter((h) => !taken.has(h.id));
  const full = max !== undefined && value.length >= max;

  function add(p: PopulationSummary) {
    if (full) return;
    onChange([...value, { id: p.id, name: p.name }]);
    setQ("");
    setHits([]);
  }

  return (
    <div className="relative">
      <label htmlFor={id} className="label">
        {label}
      </label>
      {value.length ? (
        <ol className="mb-2 space-y-0.5 text-small">
          {value.map((v, i) => (
            <li key={v.id} className="flex items-baseline justify-between gap-3 border-b border-rule-soft py-0.5">
              <span>
                <span className="num mr-2 text-ink-3">{i + 1}.</span>
                {v.name}
              </span>
              <button
                type="button"
                className="linkish text-caption text-ink-3"
                onClick={() => onChange(value.filter((x) => x.id !== v.id))}
                aria-label={`Remove ${v.name}`}
              >
                remove
              </button>
            </li>
          ))}
        </ol>
      ) : null}
      <input
        id={id}
        className="field"
        role="combobox"
        aria-expanded={open && options.length > 0}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={open && options[active] ? `${id}-opt-${active}` : undefined}
        disabled={full}
        value={q}
        placeholder={full ? `Maximum of ${max} reached` : "Search the library"}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => Math.min(options.length - 1, a + 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(0, a - 1));
          } else if (e.key === "Enter") {
            e.preventDefault();
            const o = options[active];
            if (o) add(o);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
      />
      {hint ? <p className="mt-1 text-caption text-ink-3">{hint}</p> : null}
      {error ? <p className="mt-1 text-caption text-alert">{error}</p> : null}
      {open && options.length > 0 ? (
        <ul
          id={`${id}-list`}
          role="listbox"
          className="absolute z-20 mt-1 max-h-72 w-full overflow-auto border border-ink bg-paper text-small"
        >
          {options.map((o, i) => (
            <li
              key={o.id}
              id={`${id}-opt-${i}`}
              role="option"
              aria-selected={i === active}
              className={`cursor-pointer px-3 py-1.5 ${i === active ? "bg-wash" : ""}`}
              onMouseDown={(e) => {
                e.preventDefault();
                add(o);
              }}
              onMouseEnter={() => setActive(i)}
            >
              <span>{o.name}</span>
              <span className="num ml-2 text-caption text-ink-3">
                {o.region ?? ""} {bpRange(o.date_min_bp, o.date_max_bp, o.date_mean_bp)}, n = {o.n_samples}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
