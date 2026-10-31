# Reference-data pipeline

Builds Strata's reference library from the Allen Ancient DNA Resource:

```
AADR (Dataverse)  ->  curate  ->  populations/samples/publications.parquet
                       |          
                       +-------->  strata-pca-v1 coordinates + PCA model
                       |
                       +-------->  ADMIXTOOLS 2 f2 block cache
                       |
                       +-------->  MANIFEST.json (sha256 of everything)
```

## Running it

```bash
cd data/pipeline
make all                      # download -> curate -> pca -> f2 -> manifest
make curate                   # metadata only; no genotype maths
make inspect ANNO=/path/to/v66.p1_1240K_public.anno
```

Each stage is also a subcommand and each is idempotent, so an interrupted build
resumes by rerunning it:

```bash
PYTHONPATH=.:../../services/api ../../services/api/.venv/bin/python -m pipeline curate
```

### What it needs

| Stage | Requires |
|---|---|
| `download` | Harvard Dataverse (`dataverse.harvard.edu`) |
| `curate` | nothing beyond the downloaded `.anno` |
| `pca` | the HO `.geno`/`.snp`/`.ind` |
| `f2` | the 1240K genotypes **and** ADMIXTOOLS 2 via `STRATA_RSCRIPT` |

**Neither Dataverse nor ADMIXTOOLS 2 is reachable from the development
container**, so the pipeline is written to be correct and resumable and is
executed on a GitHub runner by `.github/workflows/build-reference.yml`. The
version-fragile logic — `.anno` header resolution and the QC rules — is pure and
unit-tested locally:

```bash
cd services/api && .venv/bin/python -m pytest tests/pipeline -q
```

## Modules

| Module | Role |
|---|---|
| `config.py` | every pin: AADR release, QC thresholds, PCA and f2 options |
| `anno.py` | robust `.anno` parsing — the part that breaks on a release bump |
| `panel.py` | the curated population panel and label resolution |
| `curate.py` | individual QC, deduplication, population assembly |
| `pcaspace.py` | fits `strata-pca-v1`, projects everyone into it |
| `f2stage.py` | f2 block cache via `strata.qpadm.extract_f2` |
| `download.py` | resumable, checksummed Dataverse downloads |
| `schema.py` | parquet writers matching `strata.reference` |
| `manifest.py` | `MANIFEST.json` and its verification |

Output schema: `docs/notes/reference-schema.md`.
Licensing and what may be redistributed: `docs/DATA_PROVENANCE.md`.

## Bumping the AADR release

AADR rewords `.anno` column headers between releases, so start by checking that
the parser still resolves them:

```bash
make inspect ANNO=/path/to/<new>.anno
```

`unmapped` should be empty or contain only columns the pipeline does not use. If
a required column is missing the command fails loudly, naming it. Add a
`ColumnRule` in `anno.py` keyed on the few tokens that carry the meaning rather
than on the full header string, and add a case to
`services/api/tests/pipeline/test_anno.py`.

Then set `AADR_VERSION` in `config.py` (or pass `AADR_VERSION=` to `make`).

**Only `.p1` releases may be used.** `v62.0` and `v66.0` were decommissioned
because they contained data that should not have been public; the pipeline
refuses them. See `docs/DATA_PROVENANCE.md`.

## The panel

`panel.py` is a curated list of AADR `Group ID` labels chosen to support South
Asian ancestry questions: the Indus Periphery cline (Shahr-i-Sokhta and Gonur
outliers, Rakhigarhi), the Swat Valley protohistoric transect, Roopkund,
Iranian-plateau and Anatolian Neolithic sources, Steppe MLBA (Sintashta,
Srubnaya, Andronovo), Central Asian Bronze Age, hunter-gatherer baselines, the
present-day Indian cline, the Andamanese, and enough global context for the PCA
space not to collapse onto South Asian structure alone.

Labels may end in `*` to match a prefix, because AADR splits one archaeological
group across several suffixed labels. A label that matches nothing is **reported,
not fatal** — AADR renames groups between releases, and
`MANIFEST.json.panel.unmatched_labels` is the review surface for that.

## Population keys

`populations.parquet` carries both `population_id` (Strata's slug, for display
and URLs) and `group_id` (the AADR label, verbatim). **Anything crossing into
`strata.qpadm` uses `group_id`**, because that is the string stored in the f2
cache and sent to ADMIXTOOLS.
