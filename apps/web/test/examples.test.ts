// Normalisation of the real ADMIXTOOLS 2 example records in data/examples (raw strata.qpadm
// models: `p`, `rankdrop`, `weights[].left`, `rightfix`) into the shapes the UI renders.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { asAnalysisResult, qpadmNotes, qpadmVerdict, weightsDrawable } from "@/lib/results";
import type { QpAdmResult, QpAdmRotateResult, QpWaveResult, F4StatResult } from "@/lib/types";

const DIR = path.resolve(import.meta.dirname, "../../../data/examples");
const load = (slug: string) => {
  const f = path.join(DIR, slug, "example.json");
  return fs.existsSync(f) ? (JSON.parse(fs.readFileSync(f, "utf8")) as { result: unknown; caveats: string[] }) : null;
};
const two = load("qpadm-denisova-two-neanderthal-sources");

describe.skipIf(!two)("real example records", () => {
  it("normalises a raw qpAdm result and keeps the engine verdict", () => {
    const r = asAnalysisResult(two!.result) as QpAdmResult;
    expect(r.type).toBe("qpadm");
    expect(r.weights.map((w) => w.source)).toEqual(["Altai_Neanderthal.DG", "Vindija.DG"]);
    expect(r.p_value).toBeCloseTo(0.028, 3);
    expect(r.rank_tests[0]!.rank).toBe(1);
    expect(r.feasible).toBe(false);
    expect(qpadmVerdict(r)).toBe("infeasible");
    expect(weightsDrawable(r)).toBe(false);
    expect(qpadmNotes(r)[0]!.text).toMatch(/outside \[0, 1\]/);
    expect(two!.caveats[0]).toMatch(/NOT a South Asian analysis/);
  });

  it("keeps the engine's rotation ranking and per-model verdicts", () => {
    const r = asAnalysisResult(load("qpadm-rotate-denisova-candidates")!.result) as QpAdmRotateResult;
    expect(r.type).toBe("qpadm_rotate");
    expect(r.right.length).toBeGreaterThan(0);
    const top = r.models.find((m) => m.rank === 1)!;
    expect(top.p_value).toBeGreaterThan(0.5);
    expect(qpadmVerdict(top)).toBe("infeasible");
    expect(r.rotation_caveat).toMatch(/multiple testing/);
  });

  it("recognises qpWave and f4 records", () => {
    const w = asAnalysisResult(load("qpwave-archaic-ranks")!.result) as QpWaveResult;
    expect(w.type).toBe("qpwave");
    expect(w.rank_tests.length).toBeGreaterThan(0);
    const f = asAnalysisResult(load("f4-archaic-symmetry-tests")!.result) as F4StatResult;
    expect(f.type).toBe("f4");
    expect(f.f4.length).toBe(3);
  });
});
