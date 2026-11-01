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
make fetch-f2                 # download the published f2 cache instead of building it
make onekg                    # add the 1000 Genomes South Asian panels (CHR=22 for one)
make inspect ANNO=/path/to/v66.p1_1240K_public.anno
```

Most clones do not need to run the build at all. The derived metadata and PCA
coordinates are committed, and the f2 cache — the only expensive piece — is
published as a release asset, so `make fetch-f2` is all it takes to run formal
models against the same reference the manifest describes.

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
| `fetch-f2` | network access to `github.com` only |
| `onekg` | `ftp.1000genomes.ebi.ac.uk`, and `pca` already run |

The full build has been run end to end against AADR v66.p1 (see
`data/derived/MANIFEST.json`). Some development containers cannot reach
Dataverse; there it runs on a GitHub runner via
`.github/workflows/build-reference.yml`. ADMIXTOOLS 2 comes from
`services/worker/r/install_env.sh`. The version-fragile logic — `.anno` header
resolution and the QC rules — is pure and unit-tested locally:

```bash
cd services/api && .venv/bin/python -m pytest tests/pipeline -q
```

### Resources

On a 4-core, 15 GB machine: the download is ~11 GB, `pca` peaks at roughly
8 GB (the fit runs in float32 on int8 genotypes), and `f2` first rewrites the
1240K individuals it needs from AADR's transposed `TGENO` into ordinary `GENO`
under `data/work/f2-input/` (ADMIXTOOLS 2 does not read `TGENO`). The f2 cache
lands in `data/derived/f2/`, which is gitignored: at 147 MB it is distributed as
a release asset, not committed.

Rebuilding it takes roughly 45 minutes and the full 11 GB download, so
`make fetch-f2` downloads the published asset instead. It verifies the tarball
against the `.sha256` published beside it, refuses any archive member that
would write outside the destination, and refuses a cache whose population count
disagrees with the committed `MANIFEST.json` — a cache fixes the SNP set for
every statistic computed from it, so the wrong cache would change p-values
rather than fail. `REPO=` and `TAG=` point it at a fork or a mirror.

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

### The 1000 Genomes stage

`make onekg` adds five South Asian panels from 1000 Genomes phase 3 (GIH, PJL,
BEB, STU, ITU — 489 individuals) as a second reference source, on the same SNP
set and allele orientation as everything else. It streams each autosome's VCF
and keeps only panel positions, caching per chromosome under
`data/work/onekg/`, so a partial run continues rather than restarting:

```bash
make onekg CHR=22        # one autosome, for a quick check
make onekg               # all 22; roughly 45 minutes of streaming
```

It needs `pca` to have run, because it projects into the fitted space rather
than changing it: a present-day cohort this size would otherwise dominate the
axes and move every existing coordinate. Those rows are marked `projected`.

Run `make manifest-refresh` afterwards — the stage appends to
`populations.parquet`, `samples.parquet` and the coordinates table, and the
manifest hashes must follow. Use the refresh form, not `make manifest`, unless
`download` and `curate` ran in the same working tree: a plain `manifest` rebuilds
the record from `data/work/*.json`, and without those it would write a manifest
with no source checksums and no counts. It refuses to do that, and says so. `data/work/onekg.json` records the per-chromosome counts (sites seen,
sites at a panel position, dropped as multi-allelic or on allele mismatch,
strand-flipped) so a run can be judged rather than trusted. See
`docs/DATA_PROVENANCE.md` §3b for what is and is not redistributed.
