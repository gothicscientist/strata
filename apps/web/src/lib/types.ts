/**
 * TypeScript mirror of the Strata HTTP API (prefix /api/v1).
 * Kept in lock-step with the pydantic schemas in services/api/strata/api/schemas.py.
 */

export type ISODate = string;

/* ----------------------------------------------------------------- health */

export interface Capabilities {
  qpadm: boolean;
  llm_providers: string[];
  reference_version: string | null;
  job_mode?: string;
  [key: string]: unknown;
}

export interface Health {
  status: string;
  version: string;
  capabilities: Capabilities;
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

export interface PopulationSummary {
  id: string;
  name: string;
  region: string | null;
  country?: string | null;
  period: string | null;
  date_mean_bp: number | null;
  date_min_bp: number | null;
  date_max_bp: number | null;
  n_samples: number;
  lat: number | null;
  lon: number | null;
  source_dataset: string | null;
  publication_ids: string[];
  spaces?: string[];
}

export interface Sample {
  id: string;
  name: string;
  date_mean_bp: number | null;
  date_sd_bp?: number | null;
  sex: string | null;
  lat: number | null;
  lon: number | null;
  coverage?: number | null;
  n_snps?: number | null;
  publication_id: string | null;
  qc_flags?: string[];
}

export interface PopulationDetail extends PopulationSummary {
  description?: string | null;
  samples: Sample[];
  publications: Publication[];
}

export interface Facets {
  region: string[];
  period: string[];
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
  description: string;
  explained_variance?: number[] | null;
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
  panel_overlap?: number | null;
  panel_size?: number | null;
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
}

/* ---------------------------------------------------------- analyses/jobs */

export type AnalysisKind =
  | "pca_project"
  | "nearest"
  | "admixture_fit"
  | "admixture_rotate"
  | "qpadm"
  | "qpadm_rotate";

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
  caveat: string;
}

export interface NearestHit {
  population_id: string;
  name: string;
  distance: number;
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
}

export interface Sensitivity {
  leave_one_source_out: SensitivityRow[];
  leave_one_dimension_out: SensitivityRow[];
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
  caveat: string;
}

export interface RotationModel {
  rank: number;
  sources: string[];
  weights: number[];
  distance: number;
  pruned?: string[];
}

export interface RotationResult {
  type: "admixture_rotate";
  kind: "exploratory";
  space: string;
  target: string;
  models: RotationModel[];
  n_models_evaluated: number;
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

export interface F4Residual {
  pop1: string;
  pop2: string;
  pop3: string;
  pop4: string;
  est: number;
  se: number;
  z: number;
  fit?: number | null;
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
  notes?: string[];
}

export interface QpAdmRotateModel {
  left: string[];
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
  models: QpAdmRotateModel[];
}

export type AnalysisResult =
  | PcaProjectionResult
  | NearestResult
  | AdmixtureFitResult
  | RotationResult
  | QpAdmResult
  | QpAdmRotateResult;

/* --------------------------------------------------------------- examples */

export interface ExampleSummary {
  slug: string;
  title: string;
  summary: string;
  kind: AnalysisKind;
  result_kind: ResultKind;
  tags?: string[];
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
