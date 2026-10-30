# Strata — Architecture

Strata is a monorepo with four deployable units and one offline data pipeline.

```
strata/
├── apps/web/                 Next.js 15 (App Router, TS, Tailwind, Plotly, D3), static export → Cloudflare Pages
├── services/api/             Python package `strata` + FastAPI app (`strata.api.main:app`)
│   └── strata/
│       ├── io/               input parsers + validation + harmonisation   (no network, pure)
│       ├── analysis/         PCA, distances, admixture fitting, diagnostics (pure NumPy/SciPy)
│       ├── reference/        reference library loader (populations, samples, coordinates)
│       ├── qpadm/            Python ↔ R bridge for ADMIXTOOLS 2 (subprocess, JSON I/O)
│       ├── agent/            LLM research agent: providers, tools, RAG, loop
│       ├── jobs/             Postgres job queue (FOR UPDATE SKIP LOCKED) + inline executor
│       ├── db/               SQLAlchemy 2 models, session, repositories
│       ├── security/         auth (Supabase JWT / guest tokens), at-rest encryption, retention
│       └── api/              FastAPI routers, schemas (pydantic v2), deps
├── services/worker/          Dockerfile: Python + R 4.x + ADMIXTOOLS 2; runs `python -m strata.jobs.worker`
├── data/
│   ├── pipeline/             reproducible AADR download → curate → PCA space → f2 blocks → examples
│   ├── derived/              small committed derived artefacts (parquet/json) + MANIFEST.json (sha256)
│   └── examples/             real example analyses (inputs + outputs + provenance)
├── supabase/migrations/      Postgres schema + RLS
├── infra/                    docker-compose, Cloudflare config
└── docs/                     methods, data provenance, security, deployment
```

## Core scientific contracts (Python, `services/api/strata`)

All analysis functions are pure and deterministic given a `seed`. They return pydantic
models (see `strata/analysis/types.py`) that serialise to JSON for the API and the agent.

### Coordinate spaces

* `CoordinateSpace` — a named, versioned space in which samples/populations have
  coordinates: `"g25"` (user-supplied Global25-style 25-dim scaled coordinates) or
  `"strata-pca-v1"` (Strata's own PCA computed from AADR HO by the data pipeline).
  Strata never mixes coordinates from different spaces; every result records its space.

### `strata.io`
* `parse_g25(text: str) -> G25Table` — CSV rows `Name,PC1..PC25` (header optional, comma/tab).
  Validates 25 finite numeric columns, duplicate names, plausible ranges; returns warnings.
* `parse_raw_dna(data: bytes, filename: str) -> RawGenotypes` — autodetects 23andMe v3/v4/v5,
  AncestryDNA v1/v2, FTDNA/MyHeritage CSV, and single-sample VCF. Fields: `vendor`,
  `build` (GRCh37/38 inferred from header/positions), `rsid`, `chrom`, `pos`, `allele1`, `allele2`
  as NumPy arrays; QC report (call rate, no-calls, indels dropped, het rate, sex-chrom counts).
* `harmonize(raw: RawGenotypes, panel: SnpPanel) -> HarmonizedGenotypes` — match by rsID
  (fallback chrom:pos on the same build), resolve strand flips, drop A/T and C/G ambiguous
  SNPs, encode dosage of the panel's *reference* allele (0/1/2, NaN missing). Report overlap.

### `strata.analysis`
* `pca.fit_reference_pca(G, n_components)` — smartpca-style: per-SNP mean-centering and
  scaling by sqrt(p(1-p)), randomized SVD. Exposes loadings.
* `pca.project(sample_dosages, model)` — least-squares projection on observed SNPs only
  (equivalent to smartpca `lsqproject: YES`), with shrinkage-aware note.
* `distance.nearest(target, table, k, metric="euclidean")` — ranked population distances.
* `admixture.fit(target, sources, *, method="qp"|"slsqp")` — minimise ||Σwᵢsᵢ − t||² s.t.
  wᵢ ≥ 0, Σwᵢ = 1. Returns weights, residual distance, per-dimension residuals.
* `admixture.bootstrap(target, sources_samples, n=500, seed)` — resample individuals within each
  source population → weight CIs (2.5/97.5%) and SE.
* `admixture.rotate(target, candidates, k_range, max_models, seed)` — exhaustive / greedy source
  rotation, ranked by fit distance, with parsimony (drop sources with weight < 1%).
* `admixture.sensitivity(...)` — leave-one-source-out and leave-one-dimension-out deltas.
* Every G25/PCA fit result carries `kind="exploratory"` and a fixed caveat string.

### `strata.qpadm`
* `run_qpadm(spec: QpAdmSpec) -> QpAdmResult` — writes spec JSON, calls
  `Rscript services/worker/r/qpadm.R spec.json out.json`; R uses `admixtools::qpadm()` on an
  f2 directory (`f2_dir`) or on genotype prefix (`geno_prefix`, PLINK/EIGENSTRAT). Result:
  weights, SE, z, p-value, chi-square, dof, rank-drop table, f4 diagnostics, feasible flag.
* `run_qpadm_rotate(...)`, `run_f4(...)`, `run_qpwave(...)` similarly.
* Result carries `kind="formal"`. Availability check `qpadm_available() -> bool`.

### `strata.jobs`
Postgres table `jobs(id, kind, status, payload jsonb, result jsonb, error, owner_id, created_at,
started_at, finished_at, attempts)`. Worker claims with `FOR UPDATE SKIP LOCKED`.
`STRATA_JOB_MODE=inline` runs jobs synchronously (tests, local dev without worker).
Job kinds: `pca_project`, `admixture_fit`, `admixture_rotate`, `qpadm`, `qpadm_rotate`, `report`.

### `strata.agent`
Provider-agnostic tool-calling loop (Anthropic Messages API and OpenAI Chat Completions).
Tools are JSON-schema'd wrappers over the functions above plus `search_populations`,
`retrieve_knowledge` (RAG), `compare_models`. The agent never receives raw genotypes —
only derived coordinates/IDs. Every number in an agent answer must come from a tool result;
tool results are logged per message for audit and rendered in the UI.

RAG: corpus = `docs/methods/*.md` + population/publication metadata. Default retriever is
BM25 (no external dependency); optional dense retrieval via pgvector + embeddings when
configured.

## HTTP API (FastAPI, prefix `/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| GET | /health | liveness + capability flags (qpadm, llm providers, reference version) |
| POST | /auth/guest | issue signed guest token (24h workspace) |
| GET | /reference/populations?q=&region=&period=&page= | searchable library |
| GET | /reference/populations/{id} | population detail (samples, dates, publication) |
| GET | /reference/spaces | coordinate spaces + PCA coordinates for plotting |
| GET | /reference/publications | source publications |
| POST | /datasets (multipart) | upload G25 / raw DNA; returns QC report |
| GET/DELETE | /datasets, /datasets/{id} | manage (delete = crypto-shred) |
| POST | /analyses | create analysis (kind + params) → job |
| GET | /analyses, /analyses/{id} | list / detail with result |
| GET | /analyses/{id}/report?format=html|json | reproducible report |
| GET | /jobs/{id} | job status |
| GET | /examples, /examples/{slug} | precomputed real example analyses |
| POST | /chat/sessions, /chat/sessions/{id}/messages (SSE stream) | research assistant |

## Security & privacy of genetic data
* Raw DNA files are parsed in memory; only harmonised panel dosages are stored, encrypted
  with AES-GCM (key from `STRATA_DATA_KEY`), per-dataset data key (envelope) → delete = shred.
* Guest data auto-expires (24h). No genotype data in logs, never sent to LLM providers.
* Supabase RLS restricts every row to `owner_id = auth.uid()`.
