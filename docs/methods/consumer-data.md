# Consumer Raw DNA Files: What They Can and Cannot Support

## What the file is

Consumer genotyping services (23andMe, AncestryDNA, FamilyTreeDNA, MyHeritage and others) run
a SNP array: a fixed set of several hundred thousand pre-selected variants, reported as a
genotype call per marker. A raw-data export is therefore not a sequence. It typically contains
rsID or vendor marker ID, chromosome, position and a two-allele genotype, on reference build
GRCh37 for most vendors and chip versions.

## Limitations that affect every analysis

### SNP overlap with ancient-DNA panels

Ancient genomic studies most often use the "1240k" capture panel (about 1.24 million SNPs) or
the Human Origins array (about 600,000 SNPs). A consumer array shares only part of its content
with these. After intersecting with the SNPs actually covered in a given set of ancient samples
- many of which have substantial missingness - the usable SNP count for an f-statistic can fall
to tens of thousands. Consequences:

* Standard errors on f4 and qpAdm weights scale roughly with the inverse square root of the
  number of SNPs, so low overlap produces wide intervals and little power to reject models.
* With low power, many models are "not rejected" simply because the data cannot distinguish
  them. The honest conclusion is that the data are uninformative, not that all those models
  fit.
* Always report the SNP count behind each statistic.

### Chip ascertainment

Array content is chosen for medical and genealogical utility in largely European-ancestry
cohorts: common variants, variants useful for imputation in reference panels, and known
trait-associated loci. This ascertainment distorts allele-frequency spectra and makes absolute
f-statistic magnitudes panel-dependent. The Affymetrix Human Origins array was specifically
designed with ascertainment schemes based on discovery in single individuals of known
populations, precisely so that frequency spectra would be interpretable (Patterson et al. 2012;
Lazaridis et al. 2014, *Nature* 513:409-413). Consumer arrays have no such design. Practical
rules:

* Compare statistics only within one SNP panel.
* Prefer f-statistic *ratios* and model fits over absolute magnitudes.
* Expect ancestry components rare in the discovery cohorts to be less well resolved.

### Strand, build and allele coding

Vendor files vary in strand convention, allele ordering and build. Harmonisation must match by
rsID where possible, fall back to chromosome and position on the same build, resolve strand
flips, and drop strand-ambiguous A/T and C/G SNPs, which cannot be resolved by flipping alone.
Un-resolved strand errors look like genuine but implausible ancestry, and are a frequent cause
of a sample sitting far outside the reference cloud.

### Genotype quality and missingness

Consumer arrays have per-marker call rates below 100%, occasional systematic failures on
specific chip versions, no-calls encoded in vendor-specific ways, and indels that do not map to
biallelic SNP panels. Report call rate, number of no-calls, heterozygosity and sex-chromosome
counts as QC, and treat an unusual heterozygosity rate as a sign of contamination or of a
non-standard file rather than of unusual ancestry.

### One individual, not a population

A single genome is one draw from the ancestry distribution of its ancestors. A reference
population mean is an average over individuals. Modelling one person against population means
conflates individual-level variation (including recent, idiosyncratic ancestry and the
particular recombination of four grandparents) with population-level history. Confidence
intervals from bootstrapping reference individuals do not capture this.

### Relatives, recent admixture and consanguinity

Recent admixture produces long ancestry tracts and can fit poorly in methods assuming
long-settled mixtures. Consanguinity raises homozygosity, affecting heterozygosity-based QC and
some statistics.

## What consumer data can support

* Position relative to reference populations in a documented coordinate space, with projection
  shrinkage noted (see `pca.md`).
* Exploratory coordinate fits for screening (see `g25-coordinates.md`).
* Formal qpAdm or f4 tests where SNP overlap is sufficient, with SNP counts and standard errors
  reported, and with the understanding that power is limited.
* Clear statements about what the data cannot resolve.

## What they cannot support

* Fine-scale claims (specific villages, named historical individuals or clans, exact
  percentages to multiple decimal places).
* Dating individual admixture events reliably from a single array genotype.
* Any claim about identity, nationality or group membership. Ancestry is a statement about
  statistical relatedness to sampled reference groups.

## References

* Patterson N, Moorjani P, Luo Y, et al. (2012). Ancient admixture in human history. *Genetics*
  192(3):1065-1093.
* Lazaridis I, Patterson N, Mittnik A, et al. (2014). Ancient human genomes suggest three
  ancestral populations for present-day Europeans. *Nature* 513:409-413. (Human Origins array
  and its ascertainment panels.)
* Mathieson I, Lazaridis I, Rohland N, et al. (2015). Genome-wide patterns of selection in 230
  ancient Eurasians. *Nature* 528:499-503. (1240k capture panel in use.)
* Harney E, Patterson N, Reich D, Wakeley J (2021). Assessing the performance of qpAdm.
  *Genetics* 217(4):iyaa045. (Effects of SNP count and sample size on qpAdm behaviour.)
