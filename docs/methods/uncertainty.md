# Interpreting Uncertainty in Ancestry Analyses

## The sources of uncertainty

1. **Statistical (sampling) error.** Finitely many SNPs and individuals. Quantified by block
   jackknife or bootstrap standard errors for f-statistics and qpAdm weights, and by bootstrap
   intervals for coordinate fits. Scales roughly with the inverse square root of the number of
   independent genomic blocks, so it shrinks slowly.
2. **Model error.** The target's history is more complex than any two- or three-source mixture.
   This is not reduced by more data; more data makes it easier to detect, which is why
   well-powered analyses reject simple models that are approximately right.
3. **Reference-choice error.** Which sources and which right populations are used. Usually the
   largest source of variation in applied work, and the one standard errors do not express.
   Quantified only by rotation and leave-one-out analyses.
4. **Proxy error.** Sources are stand-ins for unsampled populations. Weights are estimated for
   the proxies used; a different proxy for the same lineage can shift weights materially.
5. **Data-processing error.** Strand, build, panel overlap, missingness, contamination. Usually
   detected by QC rather than expressed as an interval.

## Reporting rules used by Strata

* Give an interval or standard error with every estimate, and the number of SNPs behind it.
* Separate exploratory from formal evidence. Never place coordinate-fit distances and qpAdm
  p-values in one ranking, and never let an exploratory fit upgrade a rejected formal model.
* State the alternatives. If five source combinations are not rejected, report five, with
  weights; do not present the one with the largest p-value as the answer (see `qpadm.md` on why
  p-values are not a ranking score).
* Report the robustness checks actually performed, and their outcome, including checks that
  undermine the preferred model.
* Distinguish "rejected", "not rejected" and "untestable with these data". Low power is a
  result, and should be stated as such.
* Avoid false precision. A weight with a standard error of 0.04 should be reported to two
  decimal places at most, and percentages derived from it rounded accordingly.
* Name the coordinate space or f2 panel; results from different spaces or panels are not
  comparable.

## Language to prefer

| Instead of | Write |
|---|---|
| "You are 23.7% Steppe" | "The model estimates 0.24 (SE 0.05) ancestry from the Steppe_MLBA proxy" |
| "This proves admixture" | "The model with sources A and B is not rejected (p = ...); models without B are rejected" |
| "The best model is X" | "X and Y are both consistent with the data; they differ in ..." |
| "Your ancestors were from Rakhigarhi" | "Your genotype is consistent with ancestry related to the Indus-periphery profile represented by that sample" |
| "G25 shows 15% ancestry" | "An exploratory coordinate fit gives weight 0.15 for this source; this is a screening result, not a formal estimate" |

## A note on consumer expectations

Commercial ancestry reports give single percentages without intervals, which sets an
expectation that scientific analysis cannot meet honestly. Explaining why the uncertainty
exists - limited SNP overlap, proxy populations, several models fitting equally well - is part
of the answer, not a caveat to be appended to it.

## References

* Harney E, Patterson N, Reich D, Wakeley J (2021). Assessing the performance of qpAdm: a
  statistical tool for studying population admixture. *Genetics* 217(4):iyaa045.
* Maier R, Flegontov P, Flegontova O, Isildak U, Changmai P, Reich D (2023). On the limits of
  fitting complex models of population history to f-statistics. *eLife* 12:e85492.
* Lawson DJ, van Dorp L, Falush D (2018). A tutorial on how not to over-interpret STRUCTURE and
  ADMIXTURE bar plots. *Nature Communications* 9:3258.
* Patterson N, Moorjani P, Luo Y, et al. (2012). Ancient admixture in human history. *Genetics*
  192(3):1065-1093.
