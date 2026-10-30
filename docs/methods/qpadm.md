# qpWave and qpAdm

## What qpAdm does

qpAdm tests whether a **target** population can be modelled as a mixture of a set of **left**
(source, or "proximate") populations, using a set of **right** (reference, or "outgroup")
populations as a scaffold, and estimates the mixture weights. It works on the matrix of f4
statistics of the form f4(left_i, left_j; right_k, right_l) and, equivalently, on f4 statistics
relating the target to the right populations. The method is described in the supplementary
material of Haak et al. (2015, *Nature* 522:207-211) and systematically evaluated by Harney,
Patterson, Reich and Wakeley (2021, *Genetics* 217(4):iyaa045). qpWave is the related test of
how many independent streams of ancestry are needed to relate two sets of populations.

Key property: qpAdm does not require the sources to be the actual admixing populations, only
populations that are *cladal* with them relative to the right set. This is what makes it usable
with imperfect proxies, and also what makes the choice of right populations decisive.

## Output and how to read it

* **Weights** - the estimated proportions, which sum to one. Weights outside [0,1] (commonly
  reported as "infeasible") mean the model is not a valid mixture and should be rejected
  regardless of its p-value.
* **Standard errors** - from a block jackknife over genomic blocks.
* **p-value** - from the chi-square goodness-of-fit of the model's rank constraint. The null
  hypothesis is that the model *is* adequate. A small p-value rejects the model.
* **Rank/chi-square table** - the fit of nested rank hypotheses, used to ask how many sources
  are needed.
* **Number of SNPs** - the amount of data behind the statistics.

### Interpreting p-values honestly

* A p-value **above** the threshold means the model is **not rejected**. It is not evidence
  that the model is correct, and it does not rank above another non-rejected model. Several
  mutually exclusive models routinely pass.
* A p-value **below** the threshold means the data are inconsistent with the model given that
  right set. This is informative, and usually more informative than a pass.
* Thresholds are conventional (0.05 and 0.01 are both in use). Because many models are often
  tested, the nominal level is not the false-positive rate of the exercise as a whole; report
  how many models were tested.
* p-values are not comparable across models with different right sets, different targets or
  different SNP counts, and a larger p-value does not mean a better model. Treating p-values as
  a model-ranking score is one of the most common errors in applied qpAdm work.
* Power depends on SNP count and on how differentiated the sources are. With few SNPs, almost
  nothing is rejected; with very many, almost everything is, because real histories are more
  complex than any two- or three-way model.

## Choice of right populations

Harney et al. (2021) show by simulation that qpAdm's behaviour depends strongly on the right
set. Requirements, in practice:

* Right populations must be **differentially related to the sources**: each source should share
  drift with at least one right population that the others do not. A right set that cannot
  distinguish two sources leaves their weights unidentifiable.
* Right populations must **not** share post-divergence drift with the target that the sources
  lack (no gene flow between the target and a right population after the sources split off);
  otherwise valid models are rejected and invalid ones can pass.
* A right population that is itself admixed from the sources is a common cause of
  hard-to-interpret failures.
* Larger right sets give more power to reject, but also more opportunities for a violated
  assumption; adding closely related right populations adds little.
* Harney et al. also find that qpAdm can be sensitive to the inclusion of a right population
  that is more closely related to the target than any source is, and that models with very few
  SNPs or very small sample sizes behave erratically.

## Rotation strategies

Because conclusions depend on the left/right split, a standard robustness procedure is
**rotation**: take a pool of candidate populations and, for each model, place some in the left
set and the remainder in the right set. Variants:

* **Source rotation** - try all subsets of candidates as sources with a fixed right set. Reports
  which source combinations are not rejected.
* **Rotating (left-right) rotation** - every candidate not used as a source becomes a right
  population. This is the scheme used in several ancient-DNA studies and is implemented as
  `qpadm_rotate` in ADMIXTOOLS 2. It explores the space of models without privileging one
  hand-chosen right set.
* **Right-set rotation / leave-one-out** - keep the model and drop or swap individual right
  populations to see whether the verdict is stable. A model whose p-value crosses the threshold
  when one right population is removed should be reported as unstable.

Maier et al. (2023) caution that large rotation exercises amount to searching for models that
pass, and that the number of non-rejected models grows with the candidate pool; the honest
report is the full set of non-rejected models with their weights, not the single best p-value.

## Procedure recommended in Strata

1. Form hypotheses and choose a target with enough SNPs to support the test.
2. Propose candidate sources and right populations from geography, dates and screening
   distances, then justify them.
3. Run the focal model(s) and record weights, SE, p-value and SNP count.
4. Rotate sources to find the set of non-rejected models; rotate or drop right populations to
   test stability.
5. Report every model tested, which were rejected, which were not, and what distinguishes them.
   Prefer the simplest non-rejected model and say explicitly that alternatives remain.

## References

* Haak W, Lazaridis I, Patterson N, et al. (2015). Massive migration from the steppe was a
  source for Indo-European languages in Europe. *Nature* 522:207-211. (qpAdm introduced in the
  supplement.)
* Harney E, Patterson N, Reich D, Wakeley J (2021). Assessing the performance of qpAdm: a
  statistical tool for studying population admixture. *Genetics* 217(4):iyaa045.
* Maier R, Flegontov P, Flegontova O, Isildak U, Changmai P, Reich D (2023). On the limits of
  fitting complex models of population history to f-statistics. *eLife* 12:e85492.
* Patterson N, Moorjani P, Luo Y, et al. (2012). Ancient admixture in human history. *Genetics*
  192(3):1065-1093.
* Reich D, Thangaraj K, Patterson N, Price AL, Singh L (2009). Reconstructing Indian population
  history. *Nature* 461:489-494. (qpWave-style rank testing.)
