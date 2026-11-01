/** Pure logic behind the analysis composer: method catalogue, validation and request building. */

import type { AnalysisCreate, AnalysisKind, Dataset } from "./types";

export type MethodKey = Extract<
  AnalysisKind,
  "pca_project" | "nearest" | "admixture_fit" | "admixture_rotate" | "qpadm" | "qpadm_rotate"
>;

export interface MethodInfo {
  key: MethodKey;
  label: string;
  formal: boolean;
  description: string;
  guidance: string;
}

export const METHODS: MethodInfo[] = [
  {
    key: "pca_project",
    label: "PCA projection",
    formal: false,
    description: "Place the sample in the reference principal-component space.",
    guidance:
      "Projection shows where a sample falls relative to reference populations. Proximity in two components can hide differences in the others; inspect several pairs of axes.",
  },
  {
    key: "nearest",
    label: "Nearest populations",
    formal: false,
    description: "Rank reference populations by distance to the sample.",
    guidance:
      "Nearest populations are a description of similarity in one coordinate space, not of descent. Closely ranked neighbours are usually indistinguishable.",
  },
  {
    key: "admixture_fit",
    label: "Exploratory admixture fit",
    formal: false,
    description: "Best non-negative mixture of chosen sources, with bootstrap intervals.",
    guidance:
      "The fit finds the convex combination of source means closest to the target. Any target can be fitted; the residual distance and the sensitivity diagnostics tell you how well. A tight fit is not evidence that admixture happened.",
  },
  {
    key: "admixture_rotate",
    label: "Source rotation",
    formal: false,
    description: "Fit every combination of candidate sources and rank the models.",
    guidance:
      "Rotation explores many models at once. Treat the ranking as a shortlist for qpAdm, not as a result in itself.",
  },
  {
    key: "qpadm",
    label: "qpAdm",
    formal: true,
    description: "Formal test of a mixture model on f4-statistics against an outgroup set.",
    guidance:
      "qpAdm asks whether the target's f4-statistics with the right populations are explained by the left populations. Choose right populations that are differentially related to the sources; a model is rejected at p < 0.01.",
  },
  {
    key: "qpadm_rotate",
    label: "qpAdm rotation",
    formal: true,
    description: "Test all subsets of candidate sources with qpAdm.",
    guidance:
      "Rotation tests every subset of the candidate left populations against a fixed right set. Several models may be non-rejected; prefer the simplest feasible one and report the others.",
  },
];

export interface PickedRef {
  id: string;
  name: string;
}

export interface ComposerState {
  method: MethodKey;
  datasetId: string;
  sample: string;
  targetPopulation: PickedRef[];
  space: string;
  k: number;
  sources: PickedRef[];
  bootstrap: number;
  seed: number;
  sensitivity: boolean;
  minSources: number;
  maxSources: number;
  maxModels: number;
  left: PickedRef[];
  right: PickedRef[];
  allsnps: boolean;
  title: string;
}

export type BuildResult = { ok: true; request: AnalysisCreate } | { ok: false; problems: string[] };

const ids = (xs: PickedRef[]) => xs.map((x) => x.id);

export function buildAnalysisRequest(s: ComposerState, ds: Dataset | null): BuildResult {
  const problems: string[] = [];
  const m = METHODS.find((x) => x.key === s.method);
  if (!m) return { ok: false, problems: ["Choose a method."] };

  const popTarget = m.formal ? s.targetPopulation[0] : undefined;
  if (!popTarget) {
    if (!ds) problems.push("Choose a dataset to analyse.");
    else if (!s.sample) problems.push("Choose a sample from the dataset.");
    if (m.formal && ds && ds.kind === "g25")
      problems.push("qpAdm needs genotypes; G25 coordinates cannot be used. Choose a raw-genotype dataset or a library population.");
  }
  if (!m.formal && !s.space) problems.push("Choose a coordinate space.");

  const params: Record<string, unknown> = {};
  switch (s.method) {
    case "pca_project":
      params.space = s.space;
      break;
    case "nearest":
      params.space = s.space;
      params.k = clampInt(s.k, 1, 200);
      params.metric = "euclidean";
      break;
    case "admixture_fit":
      if (s.sources.length < 2) problems.push("Choose at least two sources.");
      params.space = s.space;
      params.sources = ids(s.sources);
      params.bootstrap = clampInt(s.bootstrap, 0, 5000);
      params.seed = clampInt(s.seed, 0, 2 ** 31 - 1);
      params.sensitivity = s.sensitivity;
      break;
    case "admixture_rotate":
      if (s.sources.length < 2) problems.push("Choose at least two candidate sources.");
      if (s.minSources > s.maxSources) problems.push("The fewest sources cannot exceed the most sources.");
      params.space = s.space;
      params.candidates = ids(s.sources);
      params.min_sources = clampInt(s.minSources, 1, 6);
      params.max_sources = clampInt(s.maxSources, 1, 6);
      params.max_models = clampInt(s.maxModels, 1, 2000);
      params.seed = clampInt(s.seed, 0, 2 ** 31 - 1);
      break;
    case "qpadm":
    case "qpadm_rotate":
      if (s.left.length < 1) problems.push("Choose at least one left (source) population.");
      if (s.right.length < 2) problems.push("Choose at least two right populations.");
      if (s.method === "qpadm" && s.right.length > 0 && s.right.length <= s.left.length)
        problems.push("Use more right populations than left populations.");
      params[s.method === "qpadm" ? "left" : "candidates"] = ids(s.left);
      params.right = ids(s.right);
      params.allsnps = s.allsnps;
      if (s.method === "qpadm_rotate") params.max_sources = clampInt(s.maxSources, 1, 5);
      if (popTarget) params.target_population = popTarget.id;
      break;
  }

  if (problems.length) return { ok: false, problems };
  const request: AnalysisCreate = {
    kind: s.method,
    params,
    dataset_id: popTarget ? null : (ds?.id ?? null),
    target: popTarget ? popTarget.id : s.sample,
  };
  if (s.title.trim()) request.title = s.title.trim();
  return { ok: true, request };
}

function clampInt(v: number, lo: number, hi: number): number {
  if (!Number.isFinite(v)) return lo;
  return Math.min(hi, Math.max(lo, Math.round(v)));
}
