/**
 * Helpers for reading analysis results: type inference (agent tool results omit `type`),
 * and rule-based interpretation notes for qpAdm that follow standard practice.
 */

import type {
  AdmixtureFitResult,
  AnalysisResult,
  F4Residual,
  F4StatResult,
  Feasibility,
  QpAdmResult,
  QpAdmRotateResult,
  QpAdmWeight,
  QpWaveResult,
  RankTest,
} from "./types";

type Obj = Record<string, unknown>;

const KNOWN_TYPES = [
  "pca_project",
  "nearest",
  "admixture_fit",
  "admixture_rotate",
  "qpadm",
  "qpadm_rotate",
  "f4",
  "qpwave",
] as const;

export function inferResultType(r: unknown): AnalysisResult["type"] | null {
  if (!r || typeof r !== "object") return null;
  const o = r as Obj;
  for (const k of [o.type, o.analysis]) {
    if (typeof k === "string" && (KNOWN_TYPES as readonly string[]).includes(k)) return k as AnalysisResult["type"];
  }
  if (Array.isArray(o.hits)) return "nearest";
  if (Array.isArray(o.models))
    return Array.isArray(o.right) || Array.isArray(o.rightfix) ? "qpadm_rotate" : "admixture_rotate";
  if (Array.isArray(o.targets)) return "pca_project";
  if (Array.isArray(o.weights)) {
    if (o.kind === "formal" || "p_value" in o || "p" in o || Array.isArray(o.rank_tests) || Array.isArray(o.rankdrop))
      return "qpadm";
    return "admixture_fit";
  }
  if (Array.isArray(o.rankdrop) && Array.isArray(o.left)) return "qpwave";
  if (Array.isArray(o.f4)) return "f4";
  return null;
}

const num = (v: unknown): number => (typeof v === "number" ? v : Number.NaN);
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : []);

function weightsOut(v: unknown): QpAdmWeight[] {
  return (Array.isArray(v) ? v : []).map((w: Obj) => ({
    source: String(w.source ?? w.left ?? w.name ?? ""),
    weight: num(w.weight),
    se: num(w.se),
    z: num(w.z),
  }));
}

function rankTestsOut(v: unknown): RankTest[] {
  return (Array.isArray(v) ? v : []).map((t: Obj) => ({
    rank: num(t.rank ?? t.f4rank),
    dof: num(t.dof),
    chisq: num(t.chisq),
    p: num(t.p),
    dofdiff: (t.dofdiff as number | null) ?? null,
    chisqdiff: (t.chisqdiff as number | null) ?? null,
    p_nested: (t.p_nested as number | null) ?? null,
  }));
}

function feasibleFrom(o: Obj, weights: QpAdmWeight[]): boolean {
  if (typeof o.feasible === "boolean") return o.feasible;
  const f = o.feasibility as Feasibility | undefined;
  if (f && typeof f.weights_in_unit_interval === "boolean") return f.weights_in_unit_interval;
  return weights.every((w) => w.weight >= 0 && w.weight <= 1);
}

/**
 * Return the result with its `type` set and field names normalised, or null if it is not a
 * recognised analysis payload. Accepts both the job-handler shape (`p_value`, `rank_tests`,
 * `weights[].source`) and raw strata.qpadm models as stored in data/examples (`p`, `rankdrop`,
 * `weights[].left`, `rightfix`).
 */
export function asAnalysisResult(r: unknown): AnalysisResult | null {
  const t = inferResultType(r);
  if (!t) return null;
  const o = r as Obj;
  switch (t) {
    case "qpadm": {
      const weights = weightsOut(o.weights);
      const out: QpAdmResult = {
        ...(o as object),
        type: "qpadm",
        kind: "formal",
        target: String(o.target ?? ""),
        left: strs(o.left),
        right: strs(o.right),
        weights,
        p_value: num(o.p_value ?? o.p),
        chisq: num(o.chisq),
        dof: num(o.dof),
        feasible: feasibleFrom(o, weights),
        rank_tests: rankTestsOut(o.rank_tests ?? o.rankdrop),
        f4: Array.isArray(o.f4) ? (o.f4 as F4Residual[]) : [],
        feasibility: (o.feasibility as Feasibility | null | undefined) ?? null,
        verdict: (o.verdict as string | null | undefined) ?? (o.feasibility as Feasibility | undefined)?.verdict ?? null,
      };
      return out;
    }
    case "qpadm_rotate": {
      const out: QpAdmRotateResult = {
        ...(o as object),
        type: "qpadm_rotate",
        kind: "formal",
        target: String(o.target ?? ""),
        right: strs(o.right ?? o.rightfix),
        models: (Array.isArray(o.models) ? o.models : []).map((m: Obj) => {
          const weights = weightsOut(m.weights);
          const feas = (m.feasibility as Feasibility | null | undefined) ?? null;
          return {
            rank: typeof m.rank === "number" ? m.rank : undefined,
            left: strs(m.left),
            right: strs(m.right),
            p_value: num(m.p_value ?? m.p),
            chisq: num(m.chisq),
            dof: num(m.dof),
            feasible: feasibleFrom(m, weights),
            feasibility: feas,
            verdict: (m.verdict as string | null | undefined) ?? feas?.verdict ?? null,
            weights,
          };
        }),
      };
      return out;
    }
    case "qpwave": {
      const out: QpWaveResult = {
        ...(o as object),
        type: "qpwave",
        kind: "formal",
        left: strs(o.left),
        right: strs(o.right),
        rank_tests: rankTestsOut(o.rank_tests ?? o.rankdrop),
      };
      return out;
    }
    case "f4":
      return { ...(o as object), type: "f4", kind: "formal", f4: (o.f4 as F4Residual[]) ?? [] } as F4StatResult;
    default:
      return { ...(o as object), type: t } as unknown as AnalysisResult;
  }
}

export const ALPHA_REJECT = 0.01;
export const ALPHA_PLAUSIBLE = 0.05;

export interface Note {
  level: "info" | "caution" | "reject";
  text: string;
}

/** Interpretation notes for a qpAdm model. Conservative wording; never claims proof. */
export function qpadmNotes(r: QpAdmResult): Note[] {
  // Prefer the engine's pre-written feasibility reasons, rendered verbatim.
  const f = r.feasibility;
  if (f?.reasons?.length) {
    const level: Note["level"] =
      f.verdict === "rejected" || f.verdict === "infeasible" ? "reject" : f.verdict === "plausible" ? "info" : "caution";
    return f.reasons.map((text) => ({ level, text }));
  }
  const notes: Note[] = [];
  const p = r.p_value;
  if (Number.isFinite(p)) {
    if (p < ALPHA_REJECT) {
      notes.push({
        level: "reject",
        text: `The model is rejected (p = ${p.toPrecision(2)} < ${ALPHA_REJECT}): the left populations do not explain the target's f4-statistics relative to the right set.`,
      });
    } else if (p < ALPHA_PLAUSIBLE) {
      notes.push({
        level: "caution",
        text: `The fit is marginal (${ALPHA_REJECT} ≤ p < ${ALPHA_PLAUSIBLE}). Treat it as weakly supported and check sensitivity to the right set.`,
      });
    } else {
      notes.push({
        level: "info",
        text: `The model is not rejected (p = ${p.toPrecision(2)}). This is consistent with, not proof of, the proposed sources; other source sets may fit equally well.`,
      });
    }
  }
  const neg = r.weights.filter((w) => w.weight < 0 || w.weight > 1);
  if (neg.length || r.feasible === false) {
    notes.push({
      level: "reject",
      text: `Infeasible weights${neg.length ? ` (${neg.map((w) => w.source).join(", ")})` : ""}: a proportion lies outside [0, 1], so the model is not a valid admixture model even if p is high.`,
    });
  }
  const loose = r.weights.filter((w) => Number.isFinite(w.se) && w.se > 0.15);
  if (loose.length) {
    notes.push({
      level: "caution",
      text: `Large standard errors for ${loose.map((w) => w.source).join(", ")} (> 15 percentage points): the right set may not distinguish these sources well.`,
    });
  }
  const weakZ = r.weights.filter((w) => Number.isFinite(w.z) && Math.abs(w.z) < 2 && w.weight > 0);
  if (weakZ.length && r.weights.length > 1) {
    notes.push({
      level: "info",
      text: `Weights for ${weakZ.map((w) => w.source).join(", ")} are within two standard errors of zero; a simpler model without them may also fit.`,
    });
  }
  if (r.right.length < r.left.length + 1) {
    notes.push({
      level: "caution",
      text: `The right set (${r.right.length}) should exceed the number of sources (${r.left.length}) to give the test power.`,
    });
  }
  const badF4 = f4Residuals(r).filter((f) => Math.abs(f.z) > 3);
  if (badF4.length) {
    notes.push({
      level: "caution",
      text: `${badF4.length} f4 residual${badF4.length === 1 ? " exceeds" : "s exceed"} |z| = 3; see Figure 2 for the populations involved.`,
    });
  }
  return notes;
}

/** The best (lowest distance) exploratory weights, sorted by weight descending. */
export function sortedWeights(r: AdmixtureFitResult) {
  return [...r.weights].sort((a, b) => b.weight - a.weight);
}

/** Feasible, non-rejected models first, then by p descending. */
export function rankQpAdmModels(r: QpAdmRotateResult) {
  // The engine's own ranking is kept when it reports one; it is never silently re-ranked.
  if (r.models.every((m) => typeof m.rank === "number")) return [...r.models].sort((a, b) => a.rank! - b.rank!);
  return [...r.models].sort((a, b) => {
    const ok = (m: typeof a) => (m.feasible && m.p_value >= ALPHA_REJECT ? 1 : 0);
    return ok(b) - ok(a) || b.p_value - a.p_value;
  });
}

/** f4 residual z-scores, (observed - fitted) / SE, for rows where the model fit is reported. */
export function f4Residuals(r: QpAdmResult): Array<{ label: string; z: number }> {
  return (r.f4 ?? [])
    .filter((f) => f.est !== null && f.fit !== null && f.fit !== undefined && f.se)
    .map((f) => ({ label: `${f.pop3}, ${f.pop4}`, z: (f.est! - f.fit!) / f.se! }));
}

/** Verdict for a qpAdm model: the engine's feasibility verdict when present, else from p and weights. */
export function qpadmVerdict(r: Pick<QpAdmResult, "p_value" | "feasible" | "feasibility" | "verdict">): string {
  const v = r.feasibility?.verdict ?? r.verdict;
  if (v) return v;
  if (!r.feasible) return "infeasible";
  return r.p_value < ALPHA_REJECT ? "rejected" : "not rejected";
}

/** Whether mixture weights can be drawn as proportions (all in [0, 1] and the model is not infeasible). */
export function weightsDrawable(r: QpAdmResult): boolean {
  return qpadmVerdict(r) !== "infeasible" && r.weights.every((w) => Number.isFinite(w.weight) && w.weight >= 0 && w.weight <= 1);
}
