# Science core notes (strata.io, strata.analysis, strata.reference)

## Public entry points

* `strata.io`: `parse_g25(text, n_dims=25) -> G25Table`, `parse_raw_dna(bytes, filename,
  vcf_sample=None) -> RawGenotypes` (`.qc: QCReport`), `harmonize(raw, panel, counted="ref")
  -> HarmonizedGenotypes`, and EIGENSTRAT I/O: `read_eigenstrat_dataset`,
  `write_eigenstrat_dataset`, `read_geno`, `write_geno`, `read_eigenstrat_snp`,
  `read_plink_bim`, `read_panel_parquet`, `write_panel_parquet`,
  `merge_sample_into_reference`. Errors are raised as `InputFormatError(ValueError)`, with
  messages that are safe to show users.
* `strata.analysis.pca`: `fit_reference_pca(G, k, seed=)`, `project(dosages, model)`,
  `project_array`, `out_of_fold_scores`, `population_centroids`, `PCAModel.save/load` (npz).
* `strata.analysis.distance.nearest(target, CoordinateTable, k, metric, weights=, exclude=)`.
* `strata.analysis.admixture`: `fit`, `bootstrap`, `rotate`, `sensitivity` (solvers `qp`,
  `nnls`, `slsqp`).
* `strata.analysis.fstats`: `assign_blocks`, `FrequencyData.from_genotypes`, `f2`, `f3`, `f4`,
  `f2_blocks`, `block_jackknife`.
* `strata.reference`: `load_library(root=None) -> ReferenceLibrary`. It never raises when
  data is missing; check `.available` and `.missing`. Methods: `version`, `populations`,
  `search`, `search_page`, `get_population`, `publications`, `spaces`, `facets`,
  `coordinates`, `population_table`, `population_means`, `population_samples`, `snp_panel`,
  `pca_model`. The on-disk schema is in `reference-schema.md`.

Result types live in `strata/analysis/types.py` and `strata/io/types.py`. They are pydantic
models, and `model_dump(mode="json")` gives JSON-safe output. Genotype arrays are
`exclude=True`, so a dump of a parse or harmonise result never contains genotype calls.

## Conventions and contract notes

* **Dosage:** values count copies of `SnpPanel.ref`, the allele that EIGENSTRAT `.snp`
  column 5 (PLINK A1) counts. This matches ARCHITECTURE.md; `counted="alt"` gives 2 - dosage.
  `MISSING = -1` in int8 genotype matrices; NaN in float dosage arrays.
* **Exploratory fits:** every G25/PCA fit result has `kind="exploratory"` and carries
  `EXPLORATORY_CAVEAT`. `FitQuality` is a heuristic label (fit distance relative to the
  median pairwise distance between sources), and it carries its own caveat.
* **PCA shrinkage:** do not mix in-sample reference scores with projected samples. Reference
  coordinates should come from `out_of_fold_scores`, which puts them on the same scale as
  projected user samples.
* **Contract additions:** `Population.group_id` and `Sample.master_id`. The extra
  `admixture.fit` options (`dim_weights`, `quality_scale`) are optional.
* **pyproject.toml:** added ruff per-file ignores N803/N806 (matrix names such as G, X, A) for
  `strata/{io,analysis}` and their tests.
* **f-statistics:** the default jackknife block is 5 cM with genetic positions, otherwise 5 Mb.
  For pseudohaploid samples pass `ploidy=1` per individual.

## Known limitations

* `TGENO` (transposed packed) and PLINK `.bed` genotypes are not read.
* Genome build is inferred from the header, then from four landmark SNPs, then assumed to be
  GRCh37 for consumer chips (recorded in `qc.build_source`). There is no liftover.
* Genetic sex inference is a heuristic (chrX heterozygosity and chrY call rate) and is flagged
  as such in the QC report.
