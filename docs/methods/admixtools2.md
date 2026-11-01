# ADMIXTOOLS 2

## What it is

ADMIXTOOLS 2 is an R package that reimplements the classical ADMIXTOOLS programs (`qp3Pop`,
`qpDstat`, `qpWave`, `qpAdm`, `qpGraph`) with a different computational strategy, described in
Maier R, Flegontov P, Flegontova O, Isildak U, Changmai P, Reich D (2023), "On the limits of
fitting complex models of population history to f-statistics", *eLife* 12:e85492.

The central design change is **precomputed f2 blocks**. Instead of reading genotype files for
every statistic, ADMIXTOOLS 2 computes per-block f2 statistics for all population pairs once
and stores them in a directory (the `f2_dir`). Every subsequent f4, qpWave, qpAdm or qpGraph
calculation is then a fast operation on that array. This makes large model searches, such as
exhaustive qpAdm rotation over a candidate pool, practical, and it is why Strata computes an f2
directory for its reference panel as a pipeline step.

## Practical notes

* **f2 blocks are panel-specific.** A set of f2 blocks encodes a fixed SNP set, block
  definition and population grouping. Statistics from different f2 directories are not
  comparable, and adding a population requires extending the blocks.
* **`maxmiss`, `minac2` and related options** control how missing data and allele counts are
  handled when the blocks are built, and they affect every downstream statistic. Record them
  with the artefact.
* **"All SNPs" versus intersection** - computing each statistic on all SNPs available for the
  populations involved increases power but can bias results when missingness correlates with
  ancestry (see `f-statistics.md`). ADMIXTOOLS 2 exposes this choice; results should be checked
  both ways when they are close to a decision boundary.
* **Numerical agreement with the original programs.** Maier et al. report close agreement with
  the classic ADMIXTOOLS implementations; small differences arise from block definitions and
  missing-data handling, so a published statistic reproduced in ADMIXTOOLS 2 may differ in the
  last reported digit.
* **qpGraph fitting is a search, not an estimate.** The same paper's main argument is a caution:
  the space of admixture graphs that fit f-statistics well is large, many graphs fit
  indistinguishably, and automated graph search can produce confidently wrong topologies.
  Strata exposes qpAdm and f4 rather than automated graph inference for this reason.

## How Strata calls it

Formal statistics are computed by an R subprocess. Python writes a JSON specification
(target, left, right, options, f2 directory or genotype prefix), invokes
`Rscript services/worker/r/qpadm.R spec.json out.json`, and parses the JSON result into typed
models carrying `kind="formal"`. The agent never calls R directly; it goes through the job
runner so that long-running rotations execute on the worker. When R or ADMIXTOOLS 2 is not
installed, `qpadm_available()` returns false and the agent must state that only exploratory
analyses are possible.

## References

* Maier R, Flegontov P, Flegontova O, Isildak U, Changmai P, Reich D (2023). On the limits of
  fitting complex models of population history to f-statistics. *eLife* 12:e85492.
* Patterson N, Moorjani P, Luo Y, et al. (2012). Ancient admixture in human history. *Genetics*
  192(3):1065-1093. (The statistics ADMIXTOOLS 2 implements.)
* Harney E, Patterson N, Reich D, Wakeley J (2021). Assessing the performance of qpAdm. *Genetics*
  217(4):iyaa045.
