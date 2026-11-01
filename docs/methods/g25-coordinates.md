# Coordinate-Space Ancestry Modelling (Global25-style) and Its Limits

## What these coordinates are

A "G25-style" vector is a set of 25 scaled coordinates placing a sample in a fixed,
precomputed PCA-like space derived from a large reference panel. Global25 is a privately
produced coordinate set distributed by the Eurogenes project; the underlying panel, SNP set and
scaling are not formally published, so the space cannot be audited the way `smartpca` output
from a named dataset can. Strata accepts user-supplied Global25 coordinates because many users
already have them, treats them as an opaque named space (`g25`), and also offers its own
documented space (`strata-pca-v1`) computed from a public reference panel.

## The fitting procedure

Given a target vector **t** and source population mean vectors **s**_1..**s**_k, a coordinate
fit solves

> minimise || sum_i w_i **s**_i - **t** ||^2 subject to w_i >= 0 and sum_i w_i = 1

This is a non-negative least squares problem with a simplex constraint, and it always has a
solution. The residual norm ("distance") measures how well the mixture reproduces the target's
position in that space. Strata reports weights, the residual distance, per-dimension residuals,
and, when sample-level coordinates are available, bootstrap confidence intervals obtained by
resampling individuals within each source population.

## Why this is exploratory and not a test

1. **Every model returns weights.** The optimisation has no notion of statistical rejection. A
   model composed of historically impossible sources still yields a weight vector and a
   distance. There is no p-value, no standard error from the fit itself, and no null hypothesis.
2. **Dimensions are weighted arbitrarily relative to history.** The 25 coordinates are scaled by
   eigenvalue-derived factors; the resulting metric does not correspond to any population-genetic
   quantity such as f4 or drift distance.
3. **Non-identifiability.** Genetically similar sources are nearly collinear in coordinate
   space, so weights trade off between them with almost no change in distance. Small changes to
   the source list can move a weight from one population to its neighbour. Sensitivity analysis
   (leave-one-source-out, leave-one-dimension-out) is the minimum check.
4. **Distances are not comparable across spaces or targets.** A distance of 0.02 means nothing
   absolute; it is only interpretable against other fits for the same target in the same space.
5. **Projection and shrinkage.** If the target was projected into the space (as a consumer
   genotype file must be), it is biased toward the origin, which tends to favour mixtures of
   dispersed sources. See `pca.md`.
6. **Overfitting with many sources.** Allowing more sources always reduces the residual.
   Parsimony matters: prefer the smallest source set that fits, drop sources with negligible
   weight, and compare models with equal numbers of sources.

## Legitimate uses

* Screening a large reference library for plausible sources before running formal tests.
* Visualising where a sample sits relative to reference populations.
* Generating hypotheses and candidate source/right sets for qpAdm.
* Detecting gross data problems (a sample far outside the reference cloud usually indicates a
  parsing, strand or panel-overlap failure rather than exotic ancestry).

## Reporting guidance

Label every coordinate fit as exploratory. Report the space and its version, the source list,
weights with bootstrap intervals when available, the residual distance, and the results of
sensitivity checks. Do not describe coordinate weights as admixture proportions and do not rank
them against qpAdm results; formal and exploratory evidence belong in separate tables. When a
coordinate fit and a qpAdm model disagree, the f-statistic result is the evidence.

## References

* Patterson N, Price AL, Reich D (2006). Population structure and eigenanalysis. *PLoS
  Genetics* 2(12):e190. (Framework for the underlying PCA scaling.)
* Lawson DJ, van Dorp L, Falush D (2018). A tutorial on how not to over-interpret STRUCTURE and
  ADMIXTURE bar plots. *Nature Communications* 9:3258. (On over-interpretation of
  ancestry-proportion style output generally.)
* Harney E, Patterson N, Reich D, Wakeley J (2021). Assessing the performance of qpAdm: a
  statistical tool for studying population admixture. *Genetics* 217(4):iyaa045. (Why formal
  tests, and their own assumptions, are required for admixture claims.)
