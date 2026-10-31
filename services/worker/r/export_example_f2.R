#!/usr/bin/env Rscript
# Export ADMIXTOOLS 2's bundled f2 blocks to an on-disk f2 cache.
#
#   Rscript export_example_f2.R <out_dir>
#
# `admixtools::example_f2_blocks` is a 3d array of blocked f2-statistics for
# seven real populations (Altai Neanderthal, Vindija, Denisova, Mbuti, Chimp,
# Russia_Ust_Ishim and Switzerland_Bichon). Writing it to a directory makes it
# usable anywhere Strata expects an `f2_dir`, which is what lets the test suite
# and the worked examples run real qpAdm fits with no genotype data at all.
#
# These are the package's demonstration populations. They are genuine data, but
# they are archaic-hominin and Palaeolithic populations and say nothing about
# South Asian ancestry.
#
# write_f2() needs a matching array of SNP counts per block. The bundled object
# carries block sizes in its third dimnames (e.g. "l1000"), so the counts are
# reconstructed from those and are identical for every population pair, which
# is correct here: the bundled blocks were extracted with maxmiss = 0, so every
# pair used the same SNPs.

suppressWarnings(suppressMessages({
  library(admixtools)
  library(jsonlite)
}))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) {
  cat("usage: Rscript export_example_f2.R <out_dir>\n", file = stderr())
  quit(status = 2, save = "no")
}
out_dir <- args[[1]]

blocks <- admixtools::example_f2_blocks
dims <- dim(blocks)
pops <- dimnames(blocks)[[1]]
block_labels <- dimnames(blocks)[[3]]

# Block labels look like "l1234": the number of SNPs in that block.
block_lengths <- suppressWarnings(as.numeric(gsub("[^0-9.]", "", block_labels)))
if (anyNA(block_lengths) || any(block_lengths <= 0)) {
  stop("could not recover block lengths from example_f2_blocks dimnames")
}

counts <- array(
  rep(block_lengths, each = dims[1] * dims[2]),
  dim = dims,
  dimnames = dimnames(blocks)
)

dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
admixtools::write_f2(blocks, counts, out_dir, overwrite = TRUE)

# Round-trip check: the cache must read back to the same values, or every
# statistic computed from it downstream is silently wrong.
roundtrip <- admixtools::read_f2(out_dir, pops = pops)
stopifnot(identical(dim(roundtrip)[1:2], dims[1:2]))
max_diff <- max(abs(roundtrip[pops, pops, ] - blocks[pops, pops, ]), na.rm = TRUE)
if (!is.finite(max_diff) || max_diff > 1e-12) {
  stop(sprintf("f2 round-trip mismatch: max abs difference %.3g", max_diff))
}

meta <- list(
  source = "admixtools::example_f2_blocks",
  admixtools_version = as.character(utils::packageVersion("admixtools")),
  r_version = R.version.string,
  pops = as.list(pops),
  n_pops = dims[1],
  n_blocks = dims[3],
  n_snps = sum(block_lengths),
  roundtrip_max_abs_diff = max_diff,
  exported_at = format(as.POSIXlt(Sys.time(), tz = "UTC"), "%Y-%m-%dT%H:%M:%SZ"),
  note = paste(
    "Real f2-statistics bundled with ADMIXTOOLS 2 for seven archaic-hominin and",
    "Palaeolithic populations. Demonstration data: not a South Asian panel."
  )
)
writeLines(
  jsonlite::toJSON(meta, auto_unbox = TRUE, pretty = TRUE, digits = NA),
  file.path(out_dir, "strata_export.json")
)

cat(sprintf("wrote %d populations, %d blocks, %d SNPs to %s\n",
            dims[1], dims[3], as.integer(sum(block_lengths)), out_dir),
    file = stderr())
