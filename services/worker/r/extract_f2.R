#!/usr/bin/env Rscript
# Precompute blocked f2-statistics for a set of populations.
#
#   Rscript extract_f2.R spec.json out.json
#
# Spec (JSON object):
#   geno_prefix     str                EIGENSTRAT / PACKEDANCESTRYMAP / PLINK prefix
#   out_dir         str                directory to write the f2 cache into
#   pops            [str]              populations to extract (default: all in .ind/.fam)
#   inds            [str]              individuals, paired positionally with `pops`
#   blgsize         float = 0.05       jackknife block size in Morgan
#   maxmiss         float = 0          max fraction of populations missing a SNP
#   minmaf          float = 0
#   maxmaf          float = 0.5
#   minac2          bool  = false      require >=2 non-missing alleles per pop
#   auto_only       bool  = true
#   transitions     bool  = true
#   transversions   bool  = true
#   adjust_pseudohaploid bool = true
#   maxmem          int   = 8000       MB budget before chunking
#   cols_per_chunk  int   = null       force chunked extraction for wide panels
#   afprod          bool  = true       also store allele-frequency products
#   fst             bool  = true       also store Fst
#   overwrite       bool  = false
#   n_cores         int   = 1
#
# An f2 cache is the expensive, reusable part of every f-statistic: build it
# once per population panel, then run any number of qpAdm / qpWave / f4 models
# against it. The cache is self-describing (cache_metadata.json), so the
# returned metadata is enough to prove which SNP set a later model used.

local({
  here <- dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
  source(file.path(here, "common.R"), local = FALSE)
})

run_extract_f2 <- function(spec) {
  geno_prefix <- strata_scalar(strata_require(spec, "geno_prefix"))
  out_dir <- strata_scalar(strata_require(spec, "out_dir"))

  found <- any(file.exists(paste0(geno_prefix, c(".geno", ".bed", ".pgen"))))
  if (!found) stop(sprintf("no genotype files found for prefix: %s", geno_prefix))

  pops <- strata_chr(spec$pops, "pops")
  inds <- strata_chr(spec$inds, "inds")
  if (length(inds) > 0 && length(pops) != length(inds)) {
    stop("'pops' and 'inds' must be the same length when 'inds' is supplied")
  }
  if (length(pops) > 0 && length(inds) == 0 && anyDuplicated(pops)) {
    stop("'pops' contains duplicates; supply 'inds' to group several individuals into one population")
  }

  overwrite <- strata_lgl(spec$overwrite, FALSE)
  if (dir.exists(out_dir) && !overwrite) {
    existing <- list.dirs(out_dir, full.names = FALSE, recursive = FALSE)
    if (length(existing) > 0) {
      stop(sprintf("out_dir '%s' already contains an f2 cache; set overwrite=true to rebuild", out_dir))
    }
  }
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

  call_args <- list(
    pref = geno_prefix,
    outdir = out_dir,
    blgsize = strata_num(spec$blgsize, 0.05),
    maxmiss = strata_num(spec$maxmiss, 0),
    minmaf = strata_num(spec$minmaf, 0),
    maxmaf = strata_num(spec$maxmaf, 0.5),
    minac2 = strata_lgl(spec$minac2, FALSE),
    auto_only = strata_lgl(spec$auto_only, TRUE),
    transitions = strata_lgl(spec$transitions, TRUE),
    transversions = strata_lgl(spec$transversions, TRUE),
    adjust_pseudohaploid = strata_lgl(spec$adjust_pseudohaploid, TRUE),
    maxmem = strata_num(spec$maxmem, 8000),
    afprod = strata_lgl(spec$afprod, TRUE),
    fst = strata_lgl(spec$fst, TRUE),
    n_cores = strata_int(spec$n_cores, 1L),
    overwrite = overwrite,
    verbose = FALSE
  )
  if (length(pops) > 0) call_args$pops <- pops
  if (length(inds) > 0) call_args$inds <- inds
  cpc <- strata_scalar(spec$cols_per_chunk)
  if (!is.null(cpc)) call_args$cols_per_chunk <- as.integer(cpc)

  started <- Sys.time()
  do.call(admixtools::extract_f2, call_args)
  elapsed <- as.numeric(difftime(Sys.time(), started, units = "secs"))

  meta <- tryCatch(admixtools::read_f2_cache_metadata(out_dir), error = function(e) NULL)
  cached_pops <- list.dirs(out_dir, full.names = FALSE, recursive = FALSE)
  cached_pops <- setdiff(cached_pops, c("indivs", "pairs"))

  list(
    kind = "extract_f2",
    f2_dir = normalizePath(out_dir, mustWork = TRUE),
    pops = as.list(sort(cached_pops)),
    n_pops = length(cached_pops),
    n_snps = if (is.null(meta)) NULL else strata_num_or_null(meta$n_snps),
    n_blocks = if (is.null(meta)) NULL else strata_num_or_null(meta$n_blocks),
    cache_id = if (is.null(meta)) NULL else strata_scalar(meta$cache_id),
    cache_metadata = meta,
    elapsed_seconds = elapsed,
    options = list(
      blgsize = call_args$blgsize,
      maxmiss = call_args$maxmiss,
      minmaf = call_args$minmaf,
      maxmaf = call_args$maxmaf,
      auto_only = call_args$auto_only,
      transitions = call_args$transitions,
      transversions = call_args$transversions,
      adjust_pseudohaploid = call_args$adjust_pseudohaploid
    )
  )
}

strata_main(run_extract_f2)
