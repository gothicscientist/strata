/**
 * Chart colours. Six muted hues validated (dataviz validate_palette.js, light surface #ffffff):
 * adjacent-pair CVD ΔE >= 10.8, normal-vision ΔE >= 21.5, every hue >= 3:1 against white.
 * Scatter plots (all-pairs) pair every hue with a distinct marker symbol as secondary encoding;
 * regions beyond the sixth fold into a neutral "other" grey.
 */

export const SERIES = ["#2c5c94", "#c08419", "#a13f5e", "#4a9a68", "#7c6fc0", "#8a5418"] as const;
export const SYMBOLS = ["circle", "square", "diamond", "triangle-up", "cross", "triangle-down"];
export const OTHER = "#a3a3a3";
export const INK = "#000000";
export const INK_3 = "#5c5c5c";
export const RULE = "#d6d6d6";

/** Assign a fixed slot to each region by count (largest first), stable by name. */
export function regionSlots(
  regions: Array<{ region: string | null; weight?: number }>,
): Map<string, { color: string; symbol: string }> {
  const totals = new Map<string, number>();
  for (const r of regions) {
    const key = r.region ?? "Unassigned";
    totals.set(key, (totals.get(key) ?? 0) + (r.weight ?? 1));
  }
  const ordered = [...totals.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([k]) => k);
  const out = new Map<string, { color: string; symbol: string }>();
  ordered.forEach((key, i) => {
    out.set(
      key,
      i < SERIES.length
        ? { color: SERIES[i] as string, symbol: SYMBOLS[i] as string }
        : { color: OTHER, symbol: "circle-open" },
    );
  });
  return out;
}

/** Colour for the i-th source in a stacked bar (sources keep their slot across views; never cycled). */
export function sourceColor(i: number): string {
  return i < SERIES.length ? (SERIES[i] as string) : OTHER;
}
