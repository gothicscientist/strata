/**
 * SYNTHETIC test fixtures. These numbers are invented to exercise rendering and parsing
 * logic only; they are not results of any analysis and must never be shown in the UI.
 */
import type { Analysis, Dataset, NearestResult, QpAdmResult, AdmixtureFitResult } from "@/lib/types";

export const synthNearest: NearestResult = {
  type: "nearest",
  kind: "exploratory",
  space: "synthetic-space",
  target: "SYNTH_target",
  metric: "euclidean",
  hits: [
    { population_id: "SYNTH_A", name: "Synthetic A", distance: 0.0123, region: "Region 1" },
    { population_id: "SYNTH_B", name: "Synthetic B", distance: 0.0456, region: null },
  ],
  caveat: "Synthetic fixture.",
};

export const synthFit: AdmixtureFitResult = {
  type: "admixture_fit",
  kind: "exploratory",
  space: "synthetic-space",
  target: "SYNTH_target",
  method: "qp",
  weights: [
    { source: "Synthetic A", weight: 0.3, se: 0.05, ci_low: 0.2, ci_high: 0.4 },
    { source: "Synthetic B", weight: 0.7, se: 0.05, ci_low: 0.6, ci_high: 0.8 },
  ],
  distance: 0.02,
  residuals: [0.01, -0.02, 0.003],
  n_bootstrap: 100,
  sensitivity: null,
  caveat: "",
};

export const synthQpAdm: QpAdmResult = {
  type: "qpadm",
  kind: "formal",
  target: "SYNTH_target",
  left: ["Synthetic A", "Synthetic B"],
  right: ["R1", "R2", "R3", "R4"],
  weights: [
    { source: "Synthetic A", weight: 1.12, se: 0.2, z: 5.6 },
    { source: "Synthetic B", weight: -0.12, se: 0.2, z: -0.6 },
  ],
  p_value: 0.004,
  chisq: 11.2,
  dof: 2,
  feasible: false,
  rank_tests: [{ rank: 1, dof: 2, chisq: 11.2, p: 0.004 }],
  f4: [],
};

export const synthDataset: Dataset = {
  id: "00000000-0000-0000-0000-000000000001",
  name: "Synthetic upload",
  kind: "raw_dna",
  space: null,
  sample_names: ["SYNTH_1"],
  created_at: "2026-01-01T00:00:00Z",
  expires_at: null,
  qc: { vendor: "23andMe v5", build: "GRCh37", n_variants: 600000, call_rate: 0.985, warnings: ["synthetic warning"] },
  summary: {},
  input_sha256: "x",
  payload_sha256: "y",
  size_bytes: 1,
};

export function synthAnalysis(result: Analysis["result"], id: string, kind: Analysis["kind"]): Analysis {
  return {
    id,
    kind,
    title: `Synthetic ${id}`,
    status: "succeeded",
    dataset_id: null,
    params: {},
    result,
    error: null,
    job_id: null,
    created_at: "2026-01-01T00:00:00Z",
    finished_at: null,
  };
}
