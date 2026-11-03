/**
 * TypeScript mirror of the Strata HTTP API (prefix /api/v1).
 * Kept in lock-step with the pydantic schemas in services/api/strata/api/schemas.py.
 */

export type ISODate = string;

/* ----------------------------------------------------------------- health */

export interface Capabilities {
  qpadm: boolean;
  llm_providers: string[];
  llm_configured: boolean;
  llm_byok?: boolean;
  reference_version: string | null;
  reference_loaded: boolean;
  snp_panel_loaded: boolean;
  pca_space: string | null;
  job_mode: string;
  job_kinds: string[];
  storage_backend: string;
  database: string;
  auth: Record<string, boolean>;
  examples: number;
}

/** A question the installed reference panel cannot answer. */
export interface PanelLimit {
  id: string;
  severity?: string;
  summary: string;
  labels?: string[];
  /** Analysis kinds the limit applies to; absent means all of them. */
  affects?: string[];
}

export interface ReferencePanel {
  reference_version: string | null;
  aadr_version?: string | null;
  /** The standing deep-outgroup set as it resolved in this release. */
  right_set: string[];
  limits: PanelLimit[];
  matched_groups?: number | null;
  roles?: Record<string, number>;
  unavailable_labels?: Record<string, string>;
  missing_labels?: string[];
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  capabilities: Capabilities;
  notes: string[];
}

/* ------------------------------------------------------------------- auth */

export interface GuestToken {
  token: string;
  token_type?: string;
  expires_at: ISODate;
  owner_id: string;
}

/* -------------------------------------------------------------- reference */

export interface Publication {
  id: string;
  citation: string;
  year: number | null;
  doi: string | null;
  url?: string | null;
}

/** strata.reference.library.Population */
export interface PopulationSummary {
  id: string;
  group_id: string | null;
  name: string;
  region: string | null;
  country: string | null;
  lat: number | null;
  lon: number | null;
  period: string | null;
  culture: string | null;
  date_mean_bp: number | null;
  date_sd: number | null;
  date_min_bp: number | null;
  date_max_bp: number | null;
  n_samples: number;
  data_source: string;
  publication_ids: string[];
  spaces: string[];
}

/** strata.reference.library.Sample */
export interface Sample {
  id: string;
  population_id: string;
  master_id: string | null;
  sex: string | null;
  date_mean_bp: number | null;
  date_sd: number | null;
  lat: number | null;
  lon: number | null;
  country: string | null;
  locality: string | null;
  data_type: string | null;
  n_snps: number | null;
  pseudohaploid: boolean | null;
  publication_id: string | null;
  assessment: string | null;
}

export interface PopulationDetail extends PopulationSummary {
  samples: Sample[];
  publications: Publication[];
}

export interface Facets {
  region: string[];
  period: string[];
  country: string[];
  source_dataset: string[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  facets?: Facets | null;
}

export interface PopulationQuery {
  q?: string;
  region?: string;
  period?: string;
  country?: string;
  source_dataset?: string;
  min_bp?: number;
  max_bp?: number;
  space?: string;
  page?: number;
  page_size?: number;
}

export interface SpacePopulationPoint {
  population_id: string;
  name: string;
  region: string | null;
  coords: number[];
  n_samples: number;
}

export interface CoordinateSpaceInfo {
  id: string;
  name: string;
  version: string;
  n_dims: number;
  dim_names: string[];
  level: string;
  description: string;
  explained_variance_ratio: number[] | null;
  explained_variance: number[] | null;
  provenance: Record<string, unknown>;
  populations: SpacePopulationPoint[];
}

/* --------------------------------------------------------------- datasets */

export type DatasetKind = "g25" | "raw_dna" | "vcf";

export interface QCReport {
  vendor?: string | null;
  build?: string | null;
  n_variants: number;
  n_called?: number | null;
  call_rate?: number | null;
  n_no_calls?: number | null;
  n_indels_dropped?: number | null;
  het_rate?: number | null;
  sex_chrom_counts?: Record<string, number> | null;
  /** Fraction of reference-panel SNPs usable, between 0 and 1. */
  panel_overlap?: number | null;
  panel_size?: number | null;
  overlap?: { n_usable?: number; [key: string]: unknown } | null;
  n_samples?: number | null;
  warnings: string[];
  [key: string]: unknown;
}

export interface Dataset {
  id: string;
  name: string;
  kind: DatasetKind;
  space: string | null;
  sample_names: string[];
  created_at: ISODate;
  expires_at: ISODate | null;
  qc: QCReport;
  summary: Record<string, unknown>;
  input_sha256: string;
  payload_sha256: string;
  size_bytes: number;
}

/* ---------------------------------------------------------- analyses/jobs */

export type AnalysisKind =
  | "pca_project"
  | "nearest"
  | "admixture_fit"
  | "admixture_rotate"
  | "qpadm"
  | "qpadm_rotate"
  | "f4"
  | "qpwave";

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  error: string | null;
  created_at: ISODate;
  started_at: ISODate | null;
  finished_at: ISODate | null;
  attempts?: number;
  analysis_id?: string | null;
  progress?: number | null;
  provenance?: Record<string, unknown> | null;
}

export interface AnalysisCreate {
  kind: AnalysisKind;
  title?: string;
  dataset_id?: string | null;
  target?: string | null;
  params: Record<string, unknown>;
}

export interface Analysis {
  id: string;
  kind: AnalysisKind;
  title: string | null;
  status: JobStatus;
  dataset_id: string | null;
  params: Record<string, unknown>;
  result: AnalysisResult | null;
  error: string | null;
  job_id: string | null;
  created_at: ISODate;
  finished_at: ISODate | null;
  provenance?: Record<string, unknown> | null;
}

export interface AnalysisCreated {
  analysis: Analysis;
  job: Job;
}

/* -------------------------------------------------------- result payloads */

export type ResultKind = "exploratory" | "formal";

export interface ProjectedPoint {
  name: string;
  coords: number[];
}

export interface PcaProjectionResult {
  type: "pca_project";
  kind: "exploratory";
  space: string;
  targets: ProjectedPoint[];
  n_snps_used?: number | null;
  note?: string | null;
  caveat: string;
}

export interface NearestHit {
  population_id: string;
  name: string;
  distance: number;
  rank?: number;
  region?: string | null;
}

export interface NearestResult {
  type: "nearest";
  kind: "exploratory";
  space: string;
  target: string;
  metric: string;
  hits: NearestHit[];
  caveat: string;
}

export interface SourceWeight {
  source: string;
  weight: number;
  se: number | null;
  ci_low: number | null;
  ci_high: number | null;
}

export interface SensitivityRow {
  dropped: string;
  distance: number;
  delta_distance: number;
  weights?: Record<string, number>;
  max_abs_weight_change?: number;
}

export interface Sensitivity {
  leave_one_source_out: SensitivityRow[];
  leave_one_dimension_out: SensitivityRow[];
  jitter?: { sd: number; n: number; max_weight_sd: number } | null;
  stable?: boolean;
  stability_note?: string;
}

/** strata.analysis.types.FitQuality */
export interface FitQuality {
  label: "good" | "fair" | "poor";
  distance: number;
  relative_distance: number;
  best_single_source: string;
  best_single_distance: number;
  improvement_over_single: number;
  caveat: string;
}

export interface AdmixtureFitResult {
  type: "admixture_fit";
  kind: "exploratory";
  space: string;
  target: string;
  method: string;
  weights: SourceWeight[];
  distance: number;
  residuals: number[];
  n_bootstrap?: number | null;
  sensitivity?: Sensitivity | null;
  quality?: FitQuality | null;
  converged?: boolean;
  notes?: string[];
  caveat: string;
}

export interface RotationModel {
  rank: number;
  sources: string[];
  weights: number[];
  distance: number;
  n_sources?: number;
  pruned?: string[] | null;
}

export interface RotationResult {
  type: "admixture_rotate";
  kind: "exploratory";
  space: string;
  target: string;
  models: RotationModel[];
  n_models_evaluated: number;
  n_candidates?: number;
  strategy?: string;
  preferred_rank?: number | null;
  tolerance?: number;
  min_weight?: number;
  k_range?: [number, number];
  caveat: string;
}

export interface QpAdmWeight {
  source: string;
  weight: number;
  se: number;
  z: number;
}

export interface RankTest {
  rank: number;
  dof: number;
  chisq: number;
  p: number;
  dofdiff?: number | null;
  chisqdiff?: number | null;
  p_nested?: number | null;
}

/** strata.qpadm.types.F4Row */
export interface F4Residual {
  pop1: string;
  pop2: string;
  pop3: string;
  pop4: string;
  est: number | null;
  se: number | null;
  z: number | null;
  p?: number | null;
  n?: number | null;
  fit?: number | null;
}

/** strata.qpadm.interpret feasibility summary (heuristic reporting conventions). */
export type Verdict = "plausible" | "marginal" | "rejected" | "infeasible" | "undetermined";

export interface Feasibility {
  verdict: Verdict;
  reasons: string[];
  p_passes?: boolean | null;
  weights_in_unit_interval?: boolean | null;
  weights_well_determined?: boolean | null;
  well_conditioned?: boolean | null;
  p_threshold?: number;
  marginal_p_threshold?: number;
  note?: string;
}

export interface QpAdmResult {
  type: "qpadm";
  kind: "formal";
  target: string;
  left: string[];
  right: string[];
  weights: QpAdmWeight[];
  p_value: number;
  chisq: number;
  dof: number;
  feasible: boolean;
  rank_tests: RankTest[];
  f4?: F4Residual[];
  n_snps?: number | null;
  verdict?: string | null;
  feasibility?: Feasibility | null;
  notes?: string[];
  caveat?: string;
}

export interface QpAdmRotateModel {
  rank?: number;
  left: string[];
  right?: string[];
  verdict?: string | null;
  feasibility?: Feasibility | null;
  p_value: number;
  chisq: number;
  dof: number;
  feasible: boolean;
  weights: QpAdmWeight[];
}

export interface QpAdmRotateResult {
  type: "qpadm_rotate";
  kind: "formal";
  target: string;
  right: string[];
  leftright?: string[];
  models: QpAdmRotateModel[];
  n_models_enumerated?: number;
  n_models_tested?: number;
  caveat?: string;
  rotation_caveat?: string;
}

export interface F4StatResult {
  type: "f4";
  kind: "formal";
  f4: F4Residual[];
  n_statistics?: number;
  caveat?: string;
}

export interface QpWaveResult {
  type: "qpwave";
  kind: "formal";
  left: string[];
  right: string[];
  rank_tests: RankTest[];
  alpha?: number;
  min_rank_not_rejected?: number | null;
  caveat?: string;
}

export type AnalysisResult =
  | PcaProjectionResult
  | NearestResult
  | AdmixtureFitResult
  | RotationResult
  | QpAdmResult
  | QpAdmRotateResult
  | F4StatResult
  | QpWaveResult;

/* --------------------------------------------------------------- examples */

export interface ExampleSummary {
  slug: string;
  title: string;
  summary: string;
  kind: AnalysisKind;
  result_kind: ResultKind;
  tags?: string[];
  caveats?: string[];
}

export interface ExampleDetail extends ExampleSummary {
  description?: string | null;
  inputs: Record<string, unknown>;
  params: Record<string, unknown>;
  result: AnalysisResult;
  provenance: Record<string, unknown>;
}

/* ------------------------------------------------------------------- chat */

export interface ChatSession {
  id: string;
  created_at: ISODate;
  title?: string | null;
}

export interface ChatMessage {
  id: string;
  seq: number;
  role: "user" | "assistant";
  content: string;
  tool_calls: Array<Record<string, unknown>>;
  tool_results: Array<Record<string, unknown>>;
  grounding: Grounding | null;
  citations: string[];
  usage: Record<string, unknown> | null;
  error: string | null;
  created_at: ISODate;
}

export interface ChatSessionDetail extends ChatSession {
  dataset_ids: string[];
  updated_at: ISODate;
  messages: ChatMessage[];
}

export interface ChatSessionCreate {
  title?: string;
  dataset_ids?: string[];
}

export interface UngroundedValue {
  value: string;
  context: string;
}

export interface Grounding {
  ok: boolean;
  checked?: number;
  ungrounded: UngroundedValue[];
}

/** Events yielded by strata.agent (SSE `event:` name equals `type`). */
export type ChatEvent =
  | { type: "text_delta"; text: string }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | {
      type: "tool_result";
      id: string;
      name: string;
      ok: boolean;
      result: Record<string, unknown> | null;
      error: string | null;
      duration_ms?: number;
    }
  | { type: "saved"; message_id: string }
  | { type: "message_done"; stop_reason?: string; usage?: Record<string, number> }
  | { type: "error"; message: string; retryable?: boolean }
  | {
      type: "done";
      answer: string;
      grounding: Grounding;
      citations: string[];
      usage?: Record<string, number>;
      steps?: number;
      cancelled?: boolean;
    };
