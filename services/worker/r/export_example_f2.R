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

# --- the f2 type ------------------------------------------------------------
admixtools::write_f2(blocks, counts, out_dir, id = "f2", overwrite = TRUE)
# write_f2() writes only the per-pair files; read_f2() also needs the
# block-length sidecar, which extract_f2() normally produces.
saveRDS(block_lengths, file.path(out_dir, "block_lengths_f2.rds"))

# --- the ap type ------------------------------------------------------------
# qpadm()/qpwave() on a *directory* always request the allele-frequency-product
# type ('ap'), not 'f2': internally they call get_f2(..., afprod = TRUE), and
# f2_from_precomp() then reads `<pop>_ap.rds` and applies
# scale_ap_blocks(x, from = 0), which computes -2*x, shifts the array so its
# minimum is 0, and zeroes the diagonal.
#
# example_f2_blocks contains f2, not allele-frequency products, and ap cannot
# be recovered from f2 (f2 is a distance; ap is a Gram matrix, fixed only up to
# a choice of origin). Inventing values is not an option.
#
# Instead store the exact pre-image of the decode: ap := -f2/2, so that
# scale_ap_blocks gives -2 * (-f2/2) = f2, then shifts by a single constant
# (-min over the whole array, which is non-zero only because per-block f2
# estimates can be slightly negative after bias correction) and zeroes the
# diagonal. That shift is the same for every population pair, and every
# statistic these functions compute is a *difference* of f2 values
# -- f4 = (f2(A,D) + f2(B,C) - f2(A,C) - f2(B,D))/2, with two positive and two
# negative terms -- so it cancels exactly. qpAdm, qpWave and f4 on this cache
# are therefore numerically identical to running them on the in-memory array,
# which the check below verifies rather than assumes.
admixtools::write_f2(-blocks / 2, counts, out_dir, id = "ap", overwrite = TRUE)
saveRDS(block_lengths, file.path(out_dir, "block_lengths_ap.rds"))

# --- verification -----------------------------------------------------------
# 1. The f2 type must read back bit-for-bit.
roundtrip <- admixtools::read_f2(out_dir, pops = pops)
stopifnot(identical(dim(roundtrip)[1:2], dims[1:2]))
max_diff <- max(abs(roundtrip[pops, pops, ] - blocks[pops, pops, ]), na.rm = TRUE)
if (!is.finite(max_diff) || max_diff > 1e-12) {
  stop(sprintf("f2 round-trip mismatch: max abs difference %.3g", max_diff))
}

# 2. A real qpAdm fit must give the same numbers from the cache as from the
#    in-memory array. This is the check that actually matters: it exercises the
#    ap path end to end, including the offset argued about above.
#
#    The agreement is checked in RELATIVE terms, not absolute. qpAdm weights are
#    unconstrained and can be large (for a badly misspecified model they run to
#    tens), so an absolute bound would be meaningless on one scale and
#    unreachable on another.
#
#    Exact equality is not attainable here, and not because of a mistake:
#    scale_ap_blocks() forces the decoded array's minimum to 0, and per-block f2
#    estimates are slightly negative after bias correction (min is about -0.042
#    for this dataset), so the decode adds a uniform offset to the off-diagonal
#    entries. That offset cancels analytically in every f4 -- f4 has two positive
#    and two negative f2 terms -- and the residual is floating-point error
#    amplified by the inversion of the f4 variance matrix (reciprocal condition
#    number about 4e-3 here, so roughly 250x). Measured agreement is ~1e-10
#    relative, i.e. about ten significant figures, which is some eight orders of
#    magnitude finer than the jackknife standard errors on the same quantities.
left <- c("Altai_Neanderthal.DG", "Vindija.DG")
right <- c("Chimp.REF", "Mbuti.DG", "Russia_Ust_Ishim.DG", "Switzerland_Bichon.SG")
target <- "Denisova.DG"
fit_mem <- admixtools::qpadm(blocks, left, right, target, verbose = FALSE)
fit_dir <- admixtools::qpadm(out_dir, left, right, target, verbose = FALSE)

rel_diff <- function(a, b) {
  a <- as.numeric(a)
  b <- as.numeric(b)
  keep <- is.finite(a) & is.finite(b)
  if (!any(keep)) return(0)
  scale <- pmax(abs(a[keep]), abs(b[keep]), 1e-12)
  max(abs(a[keep] - b[keep]) / scale)
}

qpadm_max_rel_diff <- max(
  rel_diff(fit_mem$rankdrop$p, fit_dir$rankdrop$p),
  rel_diff(fit_mem$rankdrop$chisq, fit_dir$rankdrop$chisq),
  rel_diff(fit_mem$weights$weight, fit_dir$weights$weight),
  rel_diff(fit_mem$weights$se, fit_dir$weights$se)
)
if (!is.finite(qpadm_max_rel_diff) || qpadm_max_rel_diff > 1e-7) {
  stop(sprintf(
    paste0("qpAdm on the exported cache disagrees with qpAdm on the in-memory ",
           "blocks (max relative difference %.3g in p / chisq / weights / SE). ",
           "The exported cache must not be used."),
    qpadm_max_rel_diff
  ))
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
  qpadm_cache_vs_memory_max_rel_diff = qpadm_max_rel_diff,
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
