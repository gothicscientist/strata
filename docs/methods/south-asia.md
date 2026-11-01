# South Asian Population History

This summary covers the published findings most often needed when analysing South Asian
ancestry. It states what the cited papers report; it is not a substitute for running the
analyses.

## The ANI-ASI cline

Reich D, Thangaraj K, Patterson N, Price AL, Singh L (2009), "Reconstructing Indian population
history", *Nature* 461:489-494, showed that genetic variation among most Indian groups is well
described by a gradient between two inferred ancestral components, which they named **Ancestral
North Indian (ANI)**, related to West Eurasians (including Central Asians, Middle Easterners,
Caucasians and Europeans), and **Ancestral South Indian (ASI)**, not closely related to any
population outside the subcontinent. Groups across the subcontinent fall along this cline, with
ANI proportion varying systematically with geography, language family and traditional social
group. The paper also reported strong founder effects and endogamy in many groups, which is why
individual-level inference in South Asia must account for high levels of relatedness and
group-specific drift.

Note that ANI and ASI are *inferred, unsampled* ancestral components, not populations that
exist as reference samples. Modelling a modern South Asian individual therefore uses proxies.

## Ancient DNA and the three-source picture

Narasimhan VM, Patterson N, Moorjani P, et al. (2019), "The formation of human populations in
South and Central Asia", *Science* 365:eaat7487, assembled a large ancient genomic dataset from
Central and South Asia. Its principal findings, as reported:

* South Asian populations are modelled with contributions from (i) a local South Asian
  hunter-gatherer-related lineage, (ii) Iranian-plateau-related ancestry, and (iii)
  Steppe pastoralist-related ancestry arriving later.
* A group of individuals from sites in Central Asia and one outlier at Gonur, plus individuals
  from the Indus periphery, carry a mixture of Iranian-related and South-Asian-hunter-gatherer-
  related ancestry without Steppe ancestry; these are treated as a proxy for the ancestry of
  Indus Valley Civilisation populations.
* Steppe-related ancestry (Middle to Late Bronze Age steppe, "Steppe_MLBA") is present in
  later South Asian groups and is correlated with traditional priestly status in some
  present-day groups, which the authors discuss in relation to the spread of Indo-European
  languages.
* The ASI component is modelled as a mixture of the indigenous South Asian lineage with
  Iranian-related ancestry, i.e. ASI itself is not a pristine lineage.

Shinde V, Narasimhan VM, Rohland N, et al. (2019), "An ancient Harappan genome lacks ancestry
from Steppe pastoralists or Iranian farmers", *Cell* 179:729-735, reported a single
low-coverage genome from Rakhigarhi, a major Indus Valley Civilisation site. Its ancestry is
consistent with the Indus-periphery profile: a mixture of a South Asian
hunter-gatherer-related lineage and an Iranian-plateau-related lineage that diverged from the
ancestors of Iranian farmers and herders before those groups adopted farming, and it carries no
detectable Steppe ancestry. The sample size is one individual with limited coverage, a
limitation the paper states explicitly.

## Implications for modelling

* **Three-way models are the norm.** Modern South Asian targets usually need sources
  representing an indigenous South Asian lineage, an Iranian-plateau-related lineage, and a
  Steppe-related lineage. Two-way models frequently fail for groups with substantial Steppe
  ancestry.
* **Proxies, not ancestors.** `Onge` (Andamanese) is commonly used as the least West-Eurasian-
  shifted available proxy for the indigenous South Asian lineage, but the Onge are a specific,
  highly drifted population and not an ASI sample. Similarly, Iranian Neolithic samples
  (e.g. from Ganj Dareh) are proxies for a lineage, not the actual contributing population.
  Weights attach to the proxies, not to historical peoples.
* **Right-population choice is delicate.** Many Eurasian populations share drift with one or
  more South Asian sources. Right sets must be checked for gene flow with the target (see
  `qpadm.md`), and conclusions should be tested by rotation.
* **Endogamy and founder effects** inflate within-group drift, which reduces qpAdm's power and
  can make group-specific drift look like a poor fit. Narasimhan et al. and Reich et al. both
  discuss this.
* **Caste, language and genetics are distinct.** The cited papers report statistical
  correlations between ancestry components and social or linguistic categories at the level of
  groups. Those correlations do not license statements about an individual's identity, and
  Strata's reports should not make them.

## References

* Reich D, Thangaraj K, Patterson N, Price AL, Singh L (2009). Reconstructing Indian population
  history. *Nature* 461:489-494.
* Narasimhan VM, Patterson N, Moorjani P, et al. (2019). The formation of human populations in
  South and Central Asia. *Science* 365:eaat7487.
* Shinde V, Narasimhan VM, Rohland N, et al. (2019). An ancient Harappan genome lacks ancestry
  from Steppe pastoralists or Iranian farmers. *Cell* 179:729-735.
* Moorjani P, Thangaraj K, Patterson N, et al. (2013). Genetic evidence for recent population
  mixture in India. *American Journal of Human Genetics* 93:422-438. (Dates the ANI-ASI mixture
  using admixture linkage disequilibrium.)
