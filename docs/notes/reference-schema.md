# `data/derived` reference artefact schema

Owner of this note: f-statistics / reference-pipeline workstream.
Normative source: `services/api/strata/reference/library.py` (`ReferenceLibrary`).
The pipeline in `data/pipeline/` writes exactly what that loader reads.

If you change the loader, change this note and `data/pipeline/pipeline/schema.py`
in the same commit.

## Layout

```
data/derived/
├── MANIFEST.json              build provenance + sha256 of every artefact
├── populations.parquet        one row per population
├── samples.parquet            one row per individual
├── publications.parquet       one row per source publication
├── spaces.json                {"spaces": [CoordinateSpace, ...]}
├── snp_panel.parquet          the SNP panel user uploads are harmonised onto
├── coordinates/
│   └── strata-pca-v1.parquet  sample_id + PC1..PCk  (one row per individual)
├── pca/
│   └── strata-pca-v1.npz      PCAModel.save() — mean, scale, loadings, ...
└── f2/
    └── strata-ref-v1/         ADMIXTOOLS 2 f2 cache (NOT committed; see below)
```

Deviation from the original brief: coordinates live at
`coordinates/<space>.parquet`, not `coordinates_<space>.parquet`, because that
is what `ReferenceLibrary._coord_frame` opens. Population-level and
sample-level coordinates share one file; the loader decides which it is by
whether a `sample_id` column exists, and derives population means itself.

## `populations.parquet`

Validated into `strata.reference.library.Population`.

| column | type | notes |
|---|---|---|
| `id` | str | stable population id; the primary key |
| `group_id` | str | **AADR `Group ID` verbatim.** The key f-statistics use |
| `name` | str | display name |
| `region` | str? | e.g. `South Asia`, `Central Asia`, `West Eurasia` |
| `country` | str? | from `Political Entity` |
| `lat`, `lon` | float? | population mean of the sample coordinates |
| `period` | str? | `Modern`, `Iron Age`, `Bronze Age`, `Neolithic`, ... |
| `culture` | str? | archaeological culture when the label implies one |
| `date_mean_bp` | float? | mean over samples, years before 1950 CE |
| `date_sd` | float? | |
| `date_min_bp`, `date_max_bp` | float? | envelope over the population's samples |
| `n_samples` | int | number of individuals that survived curation |
| `data_source` | str | `AADR-1240K` or `AADR-HO` |
| `publication_ids` | list[str] | foreign keys into `publications.parquet` |
| `spaces` | list[str] | coordinate spaces this population appears in |

`id` and `group_id` are kept separate on purpose. `id` is Strata's own slug and
may be renamed for display; `group_id` must stay byte-identical to the AADR
label because it is what ends up inside the f2 cache directory names and
therefore what `strata.qpadm` sends to ADMIXTOOLS. **Anything crossing into
`strata.qpadm` uses `group_id`.**

## `samples.parquet`

Validated into `strata.reference.library.Sample`.

| column | type | notes |
|---|---|---|
| `id` | str | AADR `Genetic ID` verbatim |
| `population_id` | str | FK to `populations.id` |
| `master_id` | str? | AADR `Master ID`; shared by duplicate individuals |
| `sex` | str? | `M` / `F` / `U` |
| `date_mean_bp`, `date_sd` | float? | |
| `lat`, `lon` | float? | |
| `country`, `locality` | str? | |
| `data_type` | str? | AADR `Data source` (e.g. `Shotgun`, `1240K`) |
| `n_snps` | int? | autosomal SNPs hit, on the panel this row came from |
| `pseudohaploid` | bool? | true for the pseudo-haploid ancient calls |
| `publication_id` | str? | |
| `assessment` | str? | AADR `ASSESSMENT` verbatim |

## `publications.parquet`

`id` (slug, e.g. `narasimhan2019`), `citation`, `year`, `doi`, `url`.

## `spaces.json`

```json
{"spaces": [{
  "id": "strata-pca-v1", "name": "Strata West-Eurasian/South-Asian PCA",
  "version": "1", "n_dims": 10, "dim_names": ["PC1", "..."],
  "level": "sample", "description": "...",
  "explained_variance_ratio": [...],
  "provenance": {"aadr_version": "...", "n_fit_individuals": 0, "...": "..."}
}]}
```

`level` is `"sample"` for `strata-pca-v1`: the file stores individual
coordinates and the loader averages them per population on demand, which is
what the bootstrap-over-individuals code path needs.

## `MANIFEST.json`

```json
{
  "version": "strata-ref-v1",
  "schema_version": "1",
  "built_at": "2026-01-01T00:00:00Z",
  "pipeline_version": "0.1.0",
  "sources": [{"name": "AADR v66.p1 1240K", "doi": "...", "url": "...",
               "sha256": "...", "retrieved_at": "..."}],
  "artefacts": {"populations.parquet": {"sha256": "...", "bytes": 0, "rows": 0}},
  "counts": {"populations": 0, "samples": 0},
  "licensing": "see docs/DATA_PROVENANCE.md"
}
```

`version` is what `ReferenceLibrary.version` reports and what
`STRATA_REFERENCE_VERSION` selects.

## What is and is not committed to git

Committed: `populations.parquet`, `samples.parquet`, `publications.parquet`,
`spaces.json`, `coordinates/*.parquet`, `MANIFEST.json`. These are small
derived metadata and coordinates.

**Not committed:** `snp_panel.parquet` (tens of MB), `pca/*.npz` (loadings are
n_snps x k), and the `f2/` caches (hundreds of MB). These are rebuilt by
`.github/workflows/build-reference.yml` and attached to a release, or rebuilt
inside the worker image. `data/raw/` and `data/work/` are gitignored.

Redistribution of AADR-derived genotypes is constrained — see
`docs/DATA_PROVENANCE.md` before adding anything genotype-shaped to git.

## f2 caches

`strata.qpadm.default_f2_dir()` resolves `STRATA_F2_DIR`, else
`data/derived/f2/$STRATA_REFERENCE_VERSION`. An f2 cache fixes the SNP set and
the filtering options, so results from two different caches are not
comparable; the cache's own `cache_metadata.json` (written by ADMIXTOOLS 2)
records `n_snps`, `n_blocks` and a `cache_id`, and the MANIFEST records that
`cache_id`.
