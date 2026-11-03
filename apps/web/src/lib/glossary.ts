/** Plain-language meanings for the terms the interface cannot avoid. One sentence each. */
export const GLOSSARY = {
  snp: {
    term: "SNP",
    plain: "One letter of DNA where people commonly differ. Consumer tests read about 600,000 of them.",
  },
  pca: {
    term: "PCA",
    plain: "A map that squeezes hundreds of thousands of DNA differences into two axes, so similar people land close together.",
  },
  admixture: {
    term: "Admixture",
    plain: "Ancestry that comes from mixing between populations that were separate for a long time.",
  },
  f4: {
    term: "f4-statistic",
    plain: "Compares four populations to ask whether two of them share more ancestry than a simple family tree allows.",
  },
  qpadm: {
    term: "qpAdm",
    plain: "A formal test: can this population be modelled as a mix of these sources, given how all of them relate to a set of outgroups?",
  },
  pvalue: {
    term: "p-value",
    plain: "How surprising the data would be if the model were right. Very small means the model is rejected.",
  },
  jackknife: {
    term: "Block jackknife",
    plain: "Error bars made by leaving out one stretch of the genome at a time and seeing how much the answer moves.",
  },
  bp: {
    term: "BP",
    plain: "Years before present, counted back from 1950.",
  },
  aadr: {
    term: "AADR",
    plain: "The Allen Ancient DNA Resource: a public, curated collection of published ancient genomes from the Reich Lab.",
  },
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
