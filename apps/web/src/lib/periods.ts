/**
 * Archaeological periods as layers of sediment: youngest (lightest) on top, oldest (darkest) at
 * the bottom. The same colour stands for the same period on every screen (landing core, library
 * filters, table swatches), so the ramp is reserved for time and never reused for regions.
 */

export type Lithology = "soil" | "sand" | "silt" | "brick" | "hatch" | "cross" | "shale" | "gravel" | "tick" | "none";

export interface PeriodStyle {
  name: string;
  color: string;
  /** Pattern drawn over the band, after the symbols of a geological section. */
  lithology: Lithology;
  /** Ink for pattern marks over this colour. */
  mark: string;
}

const ORDER: PeriodStyle[] = [
  { name: "Modern", color: "#e9ddb4", lithology: "soil", mark: "#b9a76c" },
  { name: "Early Modern", color: "#dfcb8f", lithology: "sand", mark: "#a88f48" },
  { name: "Medieval", color: "#cdae66", lithology: "silt", mark: "#8f7333" },
  { name: "Iron Age", color: "#b98a4a", lithology: "brick", mark: "#7e5823" },
  { name: "Bronze Age", color: "#a46a3a", lithology: "hatch", mark: "#6c401d" },
  { name: "Chalcolithic", color: "#7f8b62", lithology: "cross", mark: "#525c3b" },
  { name: "Neolithic", color: "#5f7f6e", lithology: "shale", mark: "#3c5648" },
  { name: "Mesolithic", color: "#4e6a7a", lithology: "gravel", mark: "#2f4553" },
  { name: "Upper Palaeolithic", color: "#34404f", lithology: "tick", mark: "#55657a" },
];

const UNKNOWN: PeriodStyle = { name: "Undated", color: "#b4b0a6", lithology: "none", mark: "#8a867c" };

const INDEX = new Map(ORDER.map((p, i) => [p.name.toLowerCase(), i]));

export function periodStyle(name: string | null | undefined): PeriodStyle {
  if (!name) return UNKNOWN;
  const i = INDEX.get(name.toLowerCase());
  return i === undefined ? { ...UNKNOWN, name } : ORDER[i]!;
}

/** Sort key: youngest first; unknown periods sink below the known ones, alphabetically. */
export function periodRank(name: string | null | undefined): number {
  if (!name) return ORDER.length + 1;
  return INDEX.get(name.toLowerCase()) ?? ORDER.length;
}

export function sortPeriods<T>(items: T[], key: (t: T) => string | null | undefined): T[] {
  return [...items].sort(
    (a, b) => periodRank(key(a)) - periodRank(key(b)) || String(key(a) ?? "").localeCompare(String(key(b) ?? "")),
  );
}
