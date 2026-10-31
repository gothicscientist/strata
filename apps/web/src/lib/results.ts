/**
 * Helpers for reading analysis results: type inference (agent tool results omit `type`),
 * and rule-based interpretation notes for qpAdm that follow standard practice.
 */

import type {
  AdmixtureFitResult,
  AnalysisResult,
  QpAdmResult,
  QpAdmRotateResult,
} from "./types";

type Obj = Record<string, unknown>;

export function inferResultType(r: unknown): AnalysisResult["type"] | null {
  if (!r || typeof r !== "object") return null;
  const o = r as Obj;
  const t = o.type;
  if (
    t === "pca_project" ||
    t === "nearest" ||
    t === "admixture_fit" ||
    t === "admixture_rotate" ||
    t === "qpadm" ||
    t === "qpadm_rotate"
  )
    return t;
  if (Array.isArray(o.hits)) return "nearest";
  if (Array.isArray(o.models)) return Array.isArray(o.right) ? "qpadm_rotate" : "admixture_rotate";
  if (Array.isArray(o.targets)) return "pca_project";
  if (Array.isArray(o.weights)) {
    if (o.kind === "formal" || "p_value" in o || Array.isArray(o.rank_tests)) return "qpadm";
    return "admixture_fit";
  }
  return null;
}

/** Return the result with its `type` set, or null if it is not a recognised analysis payload. */
export function asAnalysisResult(r: unknown): AnalysisResult | null {
  const t = inferResultType(r);
  if (!t) return null;
  return { ...(r as Obj), type: t } as unknown as AnalysisResult;
}

export const ALPHA_REJECT = 0.01;
export const ALPHA_PLAUSIBLE = 0.05;

export interface Note {
  level: "info" | "caution" | "reject";
  text: string;
}

/** Interpretation notes for a qpAdm model. Conservative wording; never claims proof. */
export function qpadmNotes(r: QpAdmResult): Note[] {
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
