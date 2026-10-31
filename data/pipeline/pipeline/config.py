"""Pinned configuration for the AADR reference pipeline.

Everything version-specific lives here so a release bump is a one-file change.

The AADR is distributed through Harvard Dataverse under
doi:10.7910/DVN/FFIDCW. Dataverse is not reachable from the development
container, so the pipeline is designed to be correct and resumable and is
executed on a GitHub runner by `.github/workflows/build-reference.yml`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PIPELINE_VERSION = "0.1.0"
REFERENCE_VERSION = os.environ.get("STRATA_REFERENCE_VERSION", "strata-ref-v1")
SCHEMA_VERSION = "1"

# --------------------------------------------------------------------------
# AADR release
# --------------------------------------------------------------------------

# v66.p1 is the current public release: June 8 2026. v62.0 and v66.0 were
# decommissioned and replaced by v62.0.p1 / v66.p1, which remove data from 161
# present-day individuals of Jacobs et al. 2019 that is only available through
# the EGA data access committee. Never point this pipeline at v62.0 or v66.0.
# See docs/DATA_PROVENANCE.md.
AADR_VERSION = os.environ.get("STRATA_AADR_VERSION", "v66.p1")
AADR_DOI = "10.7910/DVN/FFIDCW"
AADR_DATAVERSE_URL = (
    "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/FFIDCW"
)
# Dataverse's file-access endpoint; file ids come from the dataset listing.
DATAVERSE_API = "https://dataverse.harvard.edu/api"

RETIRED_AADR_VERSIONS = ("v62.0", "v66.0", "62.0", "66.0")


@dataclass(frozen=True)
class AadrDataset:
    """One AADR genotype dataset within a release.

    `stem` is the EIGENSTRAT genotype prefix as published on Dataverse, e.g.
    `v66.p1_HO.aadr.patch.PUB`, which expands to `.geno`, `.snp` and `.ind`.
    `anno_stem` is the annotation file's own basename: from v66.p1 the `.anno`
    is published without the `.patch` infix (`v66.p1_HO.aadr.PUB.anno`).
    """

    key: str
    snpset: str
    stem: str
    description: str
    anno_stem: str | None = None
    # Populated from the Dataverse dataset listing at download time; the
    # pipeline verifies against it when present and records what it saw.
    expected_sha256: str | None = None

    @property
    def anno(self) -> str:
        return f"{self.anno_stem or self.stem}.anno"

    @property
    def files(self) -> tuple[str, ...]:
        return (f"{self.stem}.geno", f"{self.stem}.snp", f"{self.stem}.ind", self.anno)


def _stem(snpset: str) -> str:
    # AADR's Dataverse file naming as of v66.p1 (read from the dataset listing
    # on 2026-10-31): genotypes are "v66.p1_HO.aadr.patch.PUB.{geno,snp,ind}".
    return f"{AADR_VERSION}_{snpset}.aadr.patch.PUB"


def _anno_stem(snpset: str) -> str:
    # ...and the annotation is "v66.p1_HO.aadr.PUB.anno", without ".patch".
    return f"{AADR_VERSION}_{snpset}.aadr.PUB"


# HO = Human Origins (~597k SNPs, includes present-day individuals genotyped on
#      the Affymetrix Human Origins array) -> PCA space.
# 1240K = the 1.24M-SNP capture panel -> f2 blocks for f-statistics.
DATASETS: dict[str, AadrDataset] = {
    "HO": AadrDataset(
        key="HO",
        snpset="HO",
        stem=_stem("HO"),
        anno_stem=_anno_stem("HO"),
        description="AADR Human Origins subset; PCA space 'strata-pca-v1'.",
    ),
    "1240K": AadrDataset(
        key="1240K",
        snpset="1240K",
        stem=_stem("1240K"),
        anno_stem=_anno_stem("1240K"),
        description="AADR 1240K capture panel; f2 blocks for qpAdm/qpWave/f4.",
    ),
}

# --------------------------------------------------------------------------
# QC thresholds
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class QcThresholds:
    """Individual-level inclusion criteria.

    `min_snps` is the headline filter: below ~30k autosomal SNPs an individual
    contributes so little to an f4-statistic that it mostly adds noise, and PCA
    projection of such a sample is dominated by shrinkage.
    """

    min_snps: int = 30_000
    # Ancient individuals only; present-day array data is complete by design.
    min_snps_modern: int = 30_000
    # AADR ASSESSMENT values that are acceptable.
    allowed_assessments: tuple[str, ...] = ("PASS",)
    # Reject if any of these appear in ASSESSMENT or ASSESSMENT WARNINGS.
    reject_assessment_substrings: tuple[str, ...] = (
        "QUESTIONABLE",
        "FAIL",
        "CRITICAL",
    )
    # AADR flags non-analysis individuals in the Group ID itself. These markers
    # cover duplicates, relatives, contamination and low coverage.
    reject_group_substrings: tuple[str, ...] = (
        "ignore",
        "_dup",
        "_contam",
        "_lc",  # low coverage
        "_rel",  # _1d_rel / _2d_rel / _rel.
        "_outlier_",  # keep bare "_outlier" labels, which are real analysis groups
        "_hasrelative",
        "_published",  # duplicate of an already-published individual
        # AADR v66.p1 hyphen markers.
        "-qcremove",
        "-dup",
        "relative",
    )
    # Drop one of each pair of individuals sharing a Master ID (same person
    # sequenced twice), keeping the one with more SNPs.
    deduplicate_on_master_id: bool = True
    # Minimum individuals for a population to be usable as an f-statistic unit.
    min_population_size: int = 1
    # Populations used as qpAdm sources/outgroups want more than one individual.
    min_population_size_for_f2: int = 1


QC = QcThresholds()

# --------------------------------------------------------------------------
# PCA space
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PcaSpaceConfig:
    space_id: str = "strata-pca-v1"
    name: str = "Strata West-Eurasian / South-Asian PCA"
    version: str = "1"
    n_components: int = 10
    seed: int = 0
    # Fit on present-day individuals only, then project ancients. This is the
    # smartpca convention (`lsqproject: YES`): ancient samples are sparse and
    # pseudo-haploid, and including them in the fit lets missingness and
    # drift define the axes.
    fit_on_modern_only: bool = True
    fit_regions: tuple[str, ...] = ("West Eurasia", "South Asia", "Central Asia")
    # Folds for out-of-fold scoring of the fit individuals. In-sample scores
    # are inflated relative to lsq-projected samples when n_snps >>
    # n_individuals, which biases any admixture fit that mixes the two.
    n_folds: int = 5
    # SNP filters applied before fitting.
    max_snp_missingness: float = 0.02
    min_maf: float = 0.01
    # LD pruning is not applied: the HO array is already ascertained and
    # smartpca-style analyses of it conventionally skip pruning.
    description: str = (
        "PCA fitted on present-day West-Eurasian, South-Asian and Central-Asian "
        "individuals from the AADR Human Origins panel; ancient individuals are "
        "projected with least-squares projection on their observed SNPs only "
        "(equivalent to smartpca lsqproject: YES). Projected coordinates are "
        "shrunk towards the origin relative to fitted ones and must not be "
        "compared to them as if they were on the same scale."
    )


PCA_SPACE = PcaSpaceConfig()

# --------------------------------------------------------------------------
# f2 blocks
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class F2Config:
    blgsize: float = 0.05  # 5 cM jackknife blocks, ADMIXTOOLS default
    maxmiss: float = 0.0  # same SNPs for every statistic: the conservative choice
    minmaf: float = 0.0
    auto_only: bool = True
    adjust_pseudohaploid: bool = True
    transitions: bool = True
    transversions: bool = True
    afprod: bool = True
    fst: bool = False  # not used downstream; skipping it halves the cache size
    n_cores: int = 1
    # Individual-level coverage floor for the f2 cache, on 1240K autosomal
    # targets. This is not a quality filter — those individuals passed QC and
    # are in samples.parquet and the PCA — it is what makes `maxmiss = 0`
    # possible at all. With maxmiss = 0 a SNP is kept only where *every*
    # population has an observation, so one sparse individual in a
    # single-individual population removes every SNP it is missing. On AADR
    # v66.p1 the curated panel of 171 populations shares **zero** autosomal
    # SNPs with no floor, 11,208 at 400k, and 229,196 at 800k (measured, not
    # estimated). The alternative is to relax maxmiss, which lets different
    # statistics rest on different SNP sets; keeping the SNP set identical for
    # every statistic and dropping the sparsest individuals is the choice
    # ADMIXTOOLS' own error message recommends.
    min_snps_for_f2: int = 800_000


F2 = F2Config()

# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Paths:
    """Filesystem layout. `raw` and `work` are gitignored."""

    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def work(self) -> Path:
        return self.root / "data" / "work"

    @property
    def derived(self) -> Path:
        return self.root / "data" / "derived"

    @property
    def examples(self) -> Path:
        return self.root / "data" / "examples"

    def aadr_dir(self, key: str) -> Path:
        return self.raw / "aadr" / AADR_VERSION / key

    def f2_dir(self, version: str = REFERENCE_VERSION) -> Path:
        return self.derived / "f2" / version


def repo_root(start: Path | None = None) -> Path:
    """Locate the monorepo root by walking up for `docs/ARCHITECTURE.md`."""
    env = os.environ.get("STRATA_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "docs" / "ARCHITECTURE.md").is_file():
            return candidate
    # data/pipeline/pipeline/config.py -> pipeline -> pipeline -> data -> root
    return Path(__file__).resolve().parents[3]


def paths(root: Path | None = None) -> Paths:
    return Paths(root=root or repo_root())


# --------------------------------------------------------------------------
# citations
# --------------------------------------------------------------------------

# Using the AADR requires citing both the Dataverse release and the manuscript.
AADR_CITATIONS: tuple[str, ...] = (
    (
        "Mallick, S., & Reich, D. (2026). The Allen Ancient DNA Resource (AADR): "
        f"A curated compendium of ancient human genomes, {AADR_VERSION}. "
        "Harvard Dataverse. https://doi.org/10.7910/DVN/FFIDCW"
    ),
    (
        "Mallick, S., Micco, A., Mah, M., Ringbauer, H., Lazaridis, I., Olalde, I., "
        "Patterson, N., & Reich, D. (2024). The Allen Ancient DNA Resource (AADR): "
        "a curated compendium of ancient human genomes. Scientific Data, 11(1). "
        "https://doi.org/10.1038/s41597-024-03031-7"
    ),
)

ADMIXTOOLS2_CITATION = (
    "Maier, R., Flegontov, P., Flegontova, O., Isildak, U., Changmai, P., & "
    "Reich, D. (2023). On the limits of fitting complex models of population "
    "history to f-statistics. eLife, 12, e85492. "
    "https://doi.org/10.7554/eLife.85492"
)


@dataclass
class BuildContext:
    """Mutable per-run state threaded through the pipeline stages."""

    paths: Paths
    aadr_version: str = AADR_VERSION
    reference_version: str = REFERENCE_VERSION
    force: bool = False
    notes: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.notes.append(message)
