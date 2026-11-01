# Data provenance, licensing and privacy

What Strata uses, where it comes from, what it may redistribute, and what it
deliberately does not.

Every claim below is marked:

* **[verified]** — read directly from a primary or near-primary source during
  development, with the source named.
* **[unverified]** — believed correct but **not** confirmed from the source
  itself, usually because the host is unreachable from the build environment
  (Harvard Dataverse, CRAN, EBI and Zenodo are all blocked there). Confirm
  before relying on it, especially before redistributing anything.

Nothing here is legal advice. If Strata is ever deployed commercially or
redistributes more than it does today, the terms below need a proper review.

---

## 1. Allen Ancient DNA Resource (AADR)

The reference panel's ancient and present-day genotypes.

| | |
|---|---|
| Publisher | David Reich Lab, Harvard Medical School |
| DOI | [10.7910/DVN/FFIDCW](https://doi.org/10.7910/DVN/FFIDCW) **[verified]** |
| Host | Harvard Dataverse **[verified]** |
| Current release | **v66.p1**, released 8 June 2026 **[verified]** |
| Datasets per release | `1240K`, `2M`, `HO` (Human Origins) **[verified]** |
| Strata uses | `HO` for the PCA space, `1240K` for f2 blocks |

**[verified]** sources for the above: the release structure, version history and
the v66.p1 date were read from the
[Poseidon AADR archive](https://github.com/poseidon-framework/aadr-archive)
(`archive.chron`, package directories) and from
[aadr2poseidon](https://github.com/poseidon-framework/aadr2poseidon)
(`AADR66.p1_adjustments/README.md`), both of which document their conversion of
the official releases and quote the official AADR changelog.

### 1.1 Citation requirement

Using the AADR **requires two citations** — the specific Dataverse release and
the manuscript. **[verified]** (stated in the
[aadr-archive README](https://github.com/poseidon-framework/aadr-archive),
quoting AADR's own instruction):

> Researchers who wish to use this compilation should provide two citations. The
> first should be to the Dataverse page and the specific version of AADR they
> use as the basis of their analyses [...]. The second should be to the
> manuscript describing AADR.

1. Mallick, S., & Reich, D. *The Allen Ancient DNA Resource (AADR): A curated
   compendium of ancient human genomes*, v66.p1. Harvard Dataverse.
   <https://doi.org/10.7910/DVN/FFIDCW>
2. Mallick, S., Micco, A., Mah, M., Ringbauer, H., Lazaridis, I., Olalde, I.,
   Patterson, N., & Reich, D. (2024). *The Allen Ancient DNA Resource (AADR): a
   curated compendium of ancient human genomes.* Scientific Data, 11(1).
   <https://doi.org/10.1038/s41597-024-03031-7> **[verified]**

These strings live in `data/pipeline/pipeline/config.py` (`AADR_CITATIONS`), are
copied into every `MANIFEST.json`, and are printed by
`python -m pipeline citations`. **Any UI or report that shows an AADR-derived
number must show them too.** The AADR is also a compendium of many underlying
studies; `publications.parquet` keeps the per-individual publication key so an
individual result can be traced to its original paper, which should be cited as
well.

### 1.2 Licence

**[verified]** — the Dataverse API record for doi:10.7910/DVN/FFIDCW
(`/api/datasets/:persistentId/?persistentId=doi:10.7910/DVN/FFIDCW`, read on
2026-10-31, dataset version 14.0 = AADR v66.p1) gives the licence as
**CC0 1.0** (`rightsIdentifier: CC0-1.0`) with an empty `termsOfUse` field. The
two-citation requirement in §1.1 is AADR's own scholarly request and is honoured
regardless.

The same listing shows the release's real file names, which the pipeline now
pins: genotypes are `v66.p1_<set>.aadr.patch.PUB.{geno,snp,ind}` and the
annotation is `v66.p1_<set>.aadr.PUB.anno`. The `.geno` files are **transposed**
packed ancestrymap (`TGENO` header), which `strata.io` reads directly and which
the f2 stage rewrites as ordinary `GENO` before handing it to ADMIXTOOLS 2. Every
file used was checked against the release's own `v66.p1__files.md5sum`.

Strata's conservative position, which holds either way:

* Strata **does not redistribute AADR genotype files.** `.geno`, `.snp`, `.ind`
  and the raw `.anno` are downloaded into `data/raw/`, which is gitignored.
* Strata commits only **derived metadata and derived statistics**: population
  and sample annotations, PCA coordinates, and f2/f4 statistics. No individual's
  genotypes can be reconstructed from these.
* `f2` block caches are derived f-statistics, not genotypes, but they are large
  and are distributed as release assets rather than committed.

### 1.3 Individuals excluded from public release

**[verified]** — quoted from the official AADR changelog via
[aadr2poseidon](https://github.com/poseidon-framework/aadr2poseidon/blob/main/AADR66.p1_adjustments/README.md):

> We have decommissioned the previously available versions of the v62.0 and
> v66.0 AADR datasets, and posted new ones v62.0.p1 and v66.p1 that are exactly
> the same except that we removed data from 161 modern individuals reported in
> Jacobs G et al. (2019) [...]
>
> The reason for removal from AADR is that we accidentally released data from
> these individuals that should only be accessible through a Data Access
> Committee hosted at the official data repository: the European
> Genome-Phenome Archive [...] accession EGAS00001003054. [...] We request that
> researchers do not use the data available through decommissioned versions of
> AADR, and that analyses of genetic data from these 161 individuals must follow
> the formal data access procedure through EGA.

Consequences, enforced in code:

* `data/pipeline/pipeline/config.py` lists `v62.0` and `v66.0` in
  `RETIRED_AADR_VERSIONS`; `python -m pipeline` **refuses to build from them**
  (`_ensure_release_is_current`), and
  `.github/workflows/build-reference.yml` fails fast before downloading.
* Only `.p1` releases may be used.

More generally, **the AADR public release is not the whole of any study.** Some
present-day populations are available only under controlled access, through a
data access committee, or on signature of a data use agreement; Strata has no
access to those and does not attempt to obtain them.

**[unverified]** — the specific claim that parts of the Human Origins
present-day panel historically required a signed letter to the Reich Lab. This
is widely repeated and plausible, but could not be confirmed against a primary
source from here. It does not affect Strata either way: Strata uses only what the
public Dataverse release contains, and redistributes none of it.

**[verified]** for v66.p1 — most of the present-day Indian groups from the
Reich-lab Human Origins panel (Chamar, Kol, Gond, Santhal, Paniya and others in
`panel.py`) and the Andamanese (Onge, Jarawa, Great Andamanese) are **absent
from the public release**: no `.ind` row in either the HO or 1240K dataset
carries those labels. They are reported in `MANIFEST.json`
`panel.unmatched_labels`. AASI-related ancestry therefore has no direct
present-day proxy in this build; `India_Harappan` (one individual) and the
Shahr-i-Sokhta / Turkmenistan BA outlier groups carry it indirectly.

### 1.4 What the pipeline excludes, and why

Documented here because exclusions are part of provenance: they change every
statistic computed downstream. Thresholds live in
`data/pipeline/pipeline/config.py` (`QcThresholds`) and the counts land in
`MANIFEST.json` under `exclusions`.

| Exclusion | Reason |
|---|---|
| Fewer than 30,000 autosomal SNPs | Contributes little to an f4-statistic and projects almost entirely as shrinkage |
| `ASSESSMENT` other than `PASS` | AADR's own quality verdict |
| `QUESTIONABLE` / `QUESTIONABLE_CRITICAL` / `FAIL` warnings | Nuclear contamination above AADR's thresholds |
| `Ignore_` group labels | AADR marks these as not for analysis |
| `_dup`, `_rel`, `_contam`, `_lc`, `_published` labels | Duplicates, relatives, contamination, low coverage |
| Shared `Master ID` | The same individual sequenced twice; the highest-coverage row is kept |

`_outlier` labels are **kept**: in AADR those are genuine analysis groups, not
quality flags, and several of them (the Shahr-i-Sokhta and Gonur outliers) are
exactly the individuals that define the Indus Periphery cline.

---

## 2. ADMIXTOOLS 2

The f-statistics engine: qpAdm, qpWave, qpDstat/f4.

| | |
|---|---|
| Repository | <https://github.com/uqrmaie1/admixtools> **[verified]** |
| Version | 2.0.10, pinned at commit `472d04e98ac8aa70e5c9cbe65722c7e5dfbe8200` **[verified]** |
| Licence | **GPL-3** — `License: GPL-3` in its `DESCRIPTION` **[verified]** |
| Citation | Maier, R., Flegontov, P., Flegontova, O., Isildak, U., Changmai, P., & Reich, D. (2023). *On the limits of fitting complex models of population history to f-statistics.* eLife 12:e85492. <https://doi.org/10.7554/eLife.85492> |

### GPL-3 and image distribution

ADMIXTOOLS 2 is GPL-3; Strata itself is AGPL-3.0-or-later, which is
GPL-3-compatible. Two consequences:

* **`services/worker` contains ADMIXTOOLS 2.** Distributing that image
  distributes GPL-3 software, which carries a corresponding-source obligation.
  The image pins the exact upstream commit and records it at
  `/opt/strata-r/ADMIXTOOLS2_COMMIT`, and `install_env.sh` reproduces the build
  from public sources; a published image should also carry a written source
  offer.
* **`services/api` deliberately contains no R and no ADMIXTOOLS 2.** qpAdm runs
  only in the worker. This keeps the public-facing image smaller and keeps GPL-3
  code out of it. `qpadm_available()` is `False` in the API image by design.

Strata calls ADMIXTOOLS 2 as a subprocess over a JSON contract
(`services/worker/r/*.R`) rather than linking to it.

### Bundled example data

`admixtools::example_f2_blocks` ships with the package: real f2-statistics for
seven populations (Altai Neanderthal, Vindija, Denisova, Mbuti, Chimp,
Russia_Ust_Ishim, Switzerland_Bichon). **[verified]** from the package's own
`man/example_f2_blocks.Rd` and `R/qpadm.R` examples.

Strata's worked examples under `data/examples/` are computed from these. They
are **genuine f-statistics on real data**, and they are **not a South Asian
analysis** — they are archaic hominins and Palaeolithic modern humans. Every
example record repeats this in its own `caveats` field. Redistributing these
derived statistics is covered by GPL-3 as applied to the package's data.

---

## 3. Global25 (Eurogenes)

Global25 ("G25") is a 25-dimensional coordinate set produced by David Wesolowski
("Davidski") of the Eurogenes project. Many users already have G25 coordinates
for their own sample and want to use them.

**Strata does not redistribute Global25 reference sheets.** Not one row.

* Users may **paste their own** G25 coordinates. Those are parsed by
  `strata.io.parse_g25` into the `"g25"` coordinate space and used only within
  that user's workspace.
* Strata ships **no** G25 population averages, scaled sheets, modern or ancient
  datasheets, and does not fetch them at runtime.
* Strata's own PCA space, `strata-pca-v1`, is built independently from AADR
  Human Origins data and is **not** a reimplementation or approximation of G25.
  Coordinates from the two spaces are never mixed: every result records its
  space, and `strata.analysis` refuses cross-space comparisons.

**[unverified]** — no authoritative, citable licence or terms-of-use statement
for the Global25 datasheets could be located by search from this environment.
That absence is precisely why the policy above is "redistribute nothing": the
sheets are a third party's compilation whose terms are not established, so the
only defensible position is to let users bring their own and to keep Strata's
reference space independent. **Do not add G25 reference data to this repository
without explicit written permission from its author.**

G25 fits are also scientifically weaker than f-statistics, and Strata labels them
accordingly: every G25/PCA result carries `kind="exploratory"`, every qpAdm
result carries `kind="formal"`, and the two are never presented as equivalent
evidence. See `docs/ARCHITECTURE.md`.

---

## 4. Consumer DNA files and user privacy

Users may upload raw data from 23andMe, AncestryDNA, FTDNA/MyHeritage, or a
single-sample VCF. Genetic data is among the most sensitive categories of
personal data: it is immutable, it identifies relatives who never consented, and
it can carry health implications far beyond ancestry.

Strata's handling, implemented in `strata.io` and `strata.security`:

* Raw uploads are parsed **in memory**. The raw file is not retained.
* Only **harmonised panel dosages** are stored, encrypted with AES-GCM under a
  per-dataset data key (envelope encryption), so deleting a dataset destroys the
  key and the data becomes unrecoverable — a crypto-shred, not a soft delete.
* **No genotype data is ever logged.** The f-statistics bridge logs script
  names, timings and population labels only; ADMIXTOOLS stderr is attached to
  exceptions rather than emitted at info level, because its progress output can
  include per-population SNP counts.
* **No genotype data is ever sent to an LLM provider.** The research agent
  receives derived coordinates, population identifiers and statistics only.
* Guest workspaces expire after 24 hours.
* Postgres row-level security restricts every row to its owner.

What Strata does not do, and should not be extended to do without a fresh
review: health or trait interpretation, relative matching across users, or
retention of raw uploads for any purpose.

---

## 5. What this repository actually commits

| Path | Committed | Contents |
|---|---|---|
| `data/raw/` | no (gitignored) | AADR downloads |
| `data/work/` | no (gitignored) | intermediate build state |
| `data/derived/populations.parquet` | yes | population metadata |
| `data/derived/samples.parquet` | yes | per-individual metadata (no genotypes) |
| `data/derived/publications.parquet` | yes | source publication keys |
| `data/derived/spaces.json` | yes | coordinate space definitions |
| `data/derived/coordinates/*.parquet` | yes | PCA coordinates |
| `data/derived/MANIFEST.json` | yes | provenance + sha256 of every artefact |
| `data/derived/snp_panel.parquet` | no | too large; a workflow artefact |
| `data/derived/pca/*.npz` | no | too large; a workflow artefact |
| `data/derived/f2/` | no | large; a release asset or rebuilt in the worker |
| `data/examples/*/example.json` | yes | real computations on ADMIXTOOLS 2's bundled data |

`MANIFEST.json` records the AADR release, the sha256 of every source file, the
QC thresholds, the exclusion counts, the f2 `cache_id` and the required
citations. `python -m pipeline verify` re-hashes the committed artefacts against
it, and the build workflow runs that before opening a pull request.

---

## 6. Open items

* ~~The exact Dataverse licence for doi:10.7910/DVN/FFIDCW~~ — resolved:
  CC0 1.0, see §1.2.
* **[unverified]** Whether any Human Origins present-day populations in the
  current public release carry additional use restrictions beyond citation.
* **[unverified]** Global25 terms of use. Until established, redistribute
  nothing.
* `publications.parquet` currently stores AADR's short publication keys without
  DOIs. Enriching them requires a bibliographic lookup that is deliberately not
  faked; until then the key is what a report can cite.
