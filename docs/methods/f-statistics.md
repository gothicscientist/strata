# f-Statistics: f2, f3 and f4

The f-statistic framework was developed by Reich, Patterson and colleagues and is set out
systematically in Patterson N, Moorjani P, Luo Y, Mallick S, Rohland N, Zhan Y, Genschoreck T,
Webster T, Reich D (2012), "Ancient admixture in human history", *Genetics* 192(3):1065-1093.
It provides tests of admixture that are based on allele-frequency correlations expected under a
tree, and that remain interpretable with the sparse, missing-heavy data typical of ancient DNA.

## Definitions

For populations A, B, C, D with sample allele frequencies a, b, c, d at a SNP, averaged over
SNPs:

* **f2(A,B) = E[(a - b)^2]** - a measure of genetic drift separating A and B.
* **f3(A; B,C) = E[(a - b)(a - c)]** - shared drift of B and C with respect to outgroup A when
  used as an *outgroup f3*, measuring how much B and C share relative to A.
* **f4(A,B; C,D) = E[(a - b)(c - d)]** - the statistic central to admixture testing.

f4 can be written as a difference of f2 values, and under a population tree in which (A,B) and
(C,D) are the two pairs separated by the internal branch, f4(A,B; C,D) has expectation zero.
A significantly non-zero f4 therefore rejects that tree and indicates gene flow between one of
A/B and one of C/D (or unmodelled structure).

## Admixture f3 and its asymmetry

f3(X; A,B) with X as the *target* is negative when X's allele frequencies are intermediate
between A and B in a way no simple tree produces; a significantly negative admixture f3 is
strong evidence that X is admixed between populations related to A and B. The test is
conservative: drift in X since admixture pushes f3 upward, so an admixed population can easily
give a non-significant or positive value, especially if the admixture was ancient or the
proxies are poor. A non-negative f3 is therefore not evidence against admixture.

By contrast, **outgroup f3**, f3(O; A,B) with O a distant outgroup, is a similarity measure
used for ranking which populations share most drift with a target.

## Standard errors

Because SNPs are correlated along a chromosome, standard errors are computed by a block
jackknife (or bootstrap) over genomic blocks, typically a few centimorgans each, rather than by
treating SNPs as independent. A Z-score is the statistic divided by its jackknife standard
error; |Z| >= 3 is the conventional threshold for significance in this literature, reflecting
the many statistics usually computed. Report Z together with the statistic, the standard error
and the number of SNPs used.

## Practical considerations

* **SNP overlap drives power.** f-statistics are computed on SNPs present in all populations
  involved (or, with the `allsnps`/useallsnps option, per-statistic subsets). Consumer genotype
  files overlapping only tens of thousands of SNPs with an ancient panel yield large standard
  errors; see `consumer-data.md`.
* **`allsnps` versus intersection.** Using all available SNPs per statistic increases power but
  can introduce bias if missingness is correlated with ancestry; Patterson et al. (2012) and the
  ADMIXTOOLS documentation both advise checking that conclusions hold under both settings.
* **Ascertainment.** f-statistic *ratios* (such as admixture proportions from f4-ratio
  estimation) are relatively robust to SNP ascertainment, but absolute magnitudes are not;
  comparing statistics computed on different SNP panels is unsafe.
* **Which populations enter matters more than how many.** A significant f4 localises gene flow
  only up to the set of populations tested; unsampled "ghost" populations related to those
  tested produce the same signal.

## f4-ratio estimation

When a target X is a mixture of sources related to A and B, and suitable outgroups exist, the
mixture proportion can be estimated as a ratio of two f4 statistics, which cancels the drift
specific to X. This is the conceptual ancestor of qpAdm (see `qpadm.md`), which generalises it
to several sources and a set of right populations and adds a goodness-of-fit test.

## References

* Patterson N, Moorjani P, Luo Y, et al. (2012). Ancient admixture in human history. *Genetics*
  192(3):1065-1093.
* Reich D, Thangaraj K, Patterson N, Price AL, Singh L (2009). Reconstructing Indian population
  history. *Nature* 461:489-494. (Introduces the f-statistic-based approach used for South Asia;
  see `south-asia.md`.)
* Maier R, Flegontov P, Flegontova O, Isildak U, Changmai P, Reich D (2023). On the limits of
  fitting complex models of population history to f-statistics. *eLife* 12:e85492.
