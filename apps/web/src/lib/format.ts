/** Number and date formatting for a typeset, journal-style presentation. */

const MINUS = "−";
const THIN = " ";

/** Use a true minus sign for negative numbers. */
export function signed(s: string): string {
  return s.startsWith("-") ? MINUS + s.slice(1) : s;
}

export function fixed(x: number | null | undefined, digits = 3): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return signed(x.toFixed(digits));
}

/** Integer with thin-space thousands grouping (SI / journal style), e.g. 12 345. */
export function int(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  const s = Math.round(Math.abs(x)).toString();
  const grouped = s.length > 4 ? s.replace(/\B(?=(\d{3})+(?!\d))/g, THIN) : s;
  return (x < 0 ? MINUS : "") + grouped;
}

/** Proportion as percent, e.g. 0.4213 -> "42.1%". */
export function pct(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  return `${signed((x * 100).toFixed(digits))}%`;
}

/** p-values: three significant digits, scientific below 0.001 (e.g. 3.2 × 10⁻⁵). */
export function pValue(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return "—";
  if (p === 0) return "< 10⁻³⁰⁰";
  if (p >= 0.001) return p.toPrecision(3).replace(/(\.\d*?[1-9])0+$|\.0+$/, "$1");
  const [m, e] = p.toExponential(1).split("e");
  return `${m} × 10${superscript(Number(e))}`;
}

const SUP: Record<string, string> = {
  "-": "⁻",
  "0": "⁰",
  "1": "¹",
  "2": "²",
  "3": "³",
  "4": "⁴",
  "5": "⁵",
  "6": "⁶",
  "7": "⁷",
  "8": "⁸",
  "9": "⁹",
};

export function superscript(n: number): string {
  return String(n)
    .split("")
    .map((c) => SUP[c] ?? c)
    .join("");
}

/** Years before present. 4500 -> "4 500 BP"; 0 or null -> em dash. */
export function bp(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  if (x <= 0) return "present";
  return `${int(x)} BP`;
}

/** A date range in BP, oldest first: "5 200–4 800 BP". Collapses equal bounds. */
export function bpRange(
  min: number | null | undefined,
  max: number | null | undefined,
  mean?: number | null,
): string {
  const lo = min ?? null;
  const hi = max ?? null;
  if (lo === null && hi === null) return bp(mean ?? null);
  if (lo === null || hi === null || lo === hi) return bp(lo ?? hi);
  const older = Math.max(lo, hi);
  const younger = Math.min(lo, hi);
  return `${int(older)}–${int(younger)} BP`;
}

/** Weight ± SE as percentages, e.g. "42.1 ± 3.4". */
export function weightSe(w: number, se: number | null | undefined): string {
  const base = signed((w * 100).toFixed(1));
  if (se === null || se === undefined || !Number.isFinite(se)) return base;
  return `${base} ± ${(se * 100).toFixed(1)}`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeExpiry(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "kept until deleted";
  const ms = Date.parse(iso) - now;
  if (!Number.isFinite(ms)) return "—";
  if (ms <= 0) return "expired";
  const h = Math.floor(ms / 3_600_000);
  if (h >= 1) return `expires in ${h} h`;
  return `expires in ${Math.max(1, Math.round(ms / 60_000))} min`;
}

export const ANALYSIS_LABEL: Record<string, string> = {
  pca_project: "PCA projection",
  nearest: "Nearest populations",
  admixture_fit: "Exploratory admixture fit",
  admixture_rotate: "Source rotation",
  qpadm: "qpAdm",
  qpadm_rotate: "qpAdm rotation",
};

export function analysisLabel(kind: string): string {
  return ANALYSIS_LABEL[kind] ?? kind;
}

export function isFormal(kind: string): boolean {
  return kind === "qpadm" || kind === "qpadm_rotate";
}
