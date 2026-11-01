# Principal Component Analysis in Population Genetics

## Purpose and interpretation

Principal component analysis (PCA) summarises genotype data as a small number of orthogonal
axes that capture the largest components of allele-frequency variation among individuals.
Applied to human genetic data it recovers, to a striking degree, geographic structure: the
leading components of European variation correspond closely to latitude and longitude
(Novembre et al. 2008, *Nature* 456:98-101). This is a descriptive summary, not a model of
history.

Patterson, Price and Reich (2006, *PLoS Genetics* 2:e190) set out the statistical framework
used by the `smartpca` program in the EIGENSOFT package, including the Tracy-Widom
distribution for deciding how many eigenvectors reflect real structure rather than noise. The
standard preprocessing centres each SNP's genotype values and divides by an estimate of
sqrt(p(1-p)), where p is the allele frequency; this weighting makes the analysis behave like a
drift-scaled analysis rather than one dominated by high-frequency variants.

## What PCA does and does not tell you

* **Position is relative.** Coordinates depend entirely on which samples are in the analysis.
  Adding or removing populations rotates and rescales the space, so coordinates from different
  runs are not comparable. Strata therefore records a named, versioned coordinate space with
  every result and refuses to mix spaces.
* **Intermediate position is ambiguous.** A sample lying between two clusters is consistent
  with admixture, but also with shared drift, a cline of continuous gene flow, or a population
  that simply diverged along an intermediate path. McVean (2009, *PLoS Genetics* 5:e1000686)
  derives the expected PCA positions under genealogical models and shows explicitly how
  admixture and ancestral structure can produce similar configurations.
* **Axes are not ancestries.** PC1 is the single direction of greatest variance, which is
  typically some combination of several historical processes. The weights of an exploratory
  coordinate fit (see `g25-coordinates.md`) are therefore not ancestry proportions in the sense
  that f-statistic methods estimate.
* **Eigenvalue magnitudes reflect sampling design.** Unequal sample sizes and the inclusion of
  closely related individuals distort the space; relatives and duplicates should be removed,
  and SNPs pruned for linkage disequilibrium, before interpreting components.

## Projection, projection bias and shrinkage

A common workflow computes a PCA from a reference panel and then *projects* additional samples
(for example, an ancient genome or a consumer genotype file) into that fixed space. Projection
avoids letting one unusual sample define its own axis, and it is the only option when the
sample has far fewer SNPs than the reference.

Projected samples are systematically pulled toward the origin. This **shrinkage** arises
because the projection of a noisy, partly missing genotype vector onto estimated eigenvectors
is attenuated relative to the position the sample would occupy had it been used in the
eigen-decomposition. The effect grows as the number of observed SNPs falls and as the reference
sample size shrinks. Consequences in practice:

* A projected ancient or low-coverage sample appears less extreme (closer to the centre of the
  cloud) than its true ancestry warrants. Distances between a projected sample and reference
  population means are therefore biased, and the bias depends on the sample's SNP count.
* Comparing a projected sample with non-projected reference individuals on the same plot
  exaggerates how "intermediate" the projected sample is.
* `smartpca`'s `lsqproject: YES` option fits each projected individual by least squares on the
  SNPs actually observed for that individual, which is the appropriate treatment for data with
  substantial and non-random missingness; it reduces, but does not remove, shrinkage.
* `smartpca` also provides `autoshrink` to correct the scale of projected samples. Any
  correction is approximate, and reporting that projection was used, with the SNP count, is more
  informative than presenting a single corrected coordinate.

Strata computes projections by least squares over the SNPs observed in the sample and attaches
a note recording the SNP overlap and the shrinkage caveat to every projected coordinate.

## Reporting guidance

State the coordinate space and its version; the number of SNPs used for the sample and for the
reference; whether the sample was projected; and the fact that distances in PCA space are
descriptive. Conclusions about admixture require f-statistic tests (`f-statistics.md`,
`qpadm.md`).

## References

* Patterson N, Price AL, Reich D (2006). Population structure and eigenanalysis. *PLoS
  Genetics* 2(12):e190.
* Novembre J, Johnson T, Bryc K, et al. (2008). Genes mirror geography within Europe. *Nature*
  456:98-101.
* McVean G (2009). A genealogical interpretation of principal components analysis. *PLoS
  Genetics* 5(10):e1000686.
* Price AL, Patterson NJ, Plenge RM, Weinblatt ME, Shadick NA, Reich D (2006). Principal
  components analysis corrects for stratification in genome-wide association studies. *Nature
  Genetics* 38:904-909.
