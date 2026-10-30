/** Side-by-side comparison of mixture models (exploratory fits and qpAdm). */

import { fixed, pValue, weightSe, pct, analysisLabel } from "./format";
import { asAnalysisResult } from "./results";
import type { Analysis } from "./types";

export interface ComparisonColumn {
  id: string;
  title: string;
  kind: "exploratory" | "formal";
}

export interface ComparisonTable {
  columns: ComparisonColumn[];
  rows: Array<{ source: string; cells: Array<string | null> }>;
  stats: Array<{ label: string; cells: Array<string | null> }>;
}

export function comparisonTable(analyses: Analysis[]): ComparisonTable {
  const columns: ComparisonColumn[] = [];
  const weights: Array<Map<string, string>> = [];
  const distance: Array<string | null> = [];
  const p: Array<string | null> = [];
  const target: Array<string | null> = [];

  for (const a of analyses) {
    const r = asAnalysisResult(a.result);
    if (!r) continue;
    if (r.type === "admixture_fit") {
      columns.push({ id: a.id, title: a.title ?? analysisLabel(a.kind), kind: "exploratory" });
      weights.push(
        new Map(
          r.weights.map((w) => [
            w.source,
            w.ci_low !== null && w.ci_high !== null
              ? `${pct(w.weight)} [${pct(w.ci_low)}, ${pct(w.ci_high)}]`
              : pct(w.weight),
          ]),
        ),
      );
      distance.push(fixed(r.distance, 4));
      p.push(null);
      target.push(r.target);
    } else if (r.type === "qpadm") {
      columns.push({ id: a.id, title: a.title ?? analysisLabel(a.kind), kind: "formal" });
      weights.push(new Map(r.weights.map((w) => [w.source, weightSe(w.weight, w.se)])));
      distance.push(null);
      p.push(pValue(r.p_value));
      target.push(r.target);
    }
  }

  const sources: string[] = [];
  for (const m of weights) for (const s of m.keys()) if (!sources.includes(s)) sources.push(s);

  const stats: ComparisonTable["stats"] = [{ label: "Target", cells: target }];
  if (distance.some((d) => d !== null)) stats.push({ label: "Residual distance", cells: distance });
  if (p.some((x) => x !== null)) stats.push({ label: "qpAdm p", cells: p });

  return {
    columns,
    rows: sources.map((s) => ({ source: s, cells: weights.map((m) => m.get(s) ?? null) })),
    stats,
  };
}
