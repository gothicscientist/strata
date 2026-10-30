#!/usr/bin/env Rscript
# qpWave via ADMIXTOOLS 2.
#
#   Rscript qpwave.R spec.json out.json
#
# Spec (JSON object):
#   left            [str]              first population set
#   right           [str]              second population set
#   f2_dir | geno_prefix               as in qpadm.R
#   fudge, auto_only, blgsize, poly_only, boot, constrained, singular_threshold
#   allsnps, maxmiss                   geno_prefix only
#   threads         int   = 1
#
# qpWave compares two population sets by fitting low-rank approximations to the
# matrix of f4-statistics between them. The rank-0 test asks whether `left` and
# `right` form two clades relative to each other; the smallest rank that is not
# rejected is a lower bound on the number of admixture waves.
#
# Output: `rankdrop` (one row per tested rank), `f4`, and `min_rank_not_rejected`
# at the significance level `alpha` (default 0.05).

local({
  here <- dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
  source(file.path(here, "common.R"), local = FALSE)
})

run_qpwave <- function(spec) {
  left <- strata_chr(strata_require(spec, "left"), "left")
  right <- strata_chr(strata_require(spec, "right"), "right")

  if (length(left) < 2) stop("'left' must contain at least two populations")
  if (length(right) < 2) stop("'right' must contain at least two populations")
  overlap <- intersect(left, right)
  if (length(overlap) > 0) {
    stop(sprintf("populations appear on both sides: %s", paste(overlap, collapse = ", ")))
  }

  resolved <- strata_resolve_data(spec)
  extra <- strata_geno_args(spec, resolved$source)
  alpha <- strata_num(spec$alpha, 0.05)

  # qpwave() has a fixed signature and does not take `...`; for genotype input
  # the allsnps/maxmiss style options have to go through qpadm(target = NULL),
  # which is exactly what qpwave() delegates to.
  base_args <- list(
    data = resolved$data,
    left = left,
    right = right,
    fudge = strata_num(spec$fudge, 1e-4),
    auto_only = strata_lgl(spec$auto_only, TRUE),
    blgsize = strata_num(spec$blgsize, 0.05),
    poly_only = strata_lgl(spec$poly_only, FALSE),
    boot = strata_scalar(spec$boot, FALSE),
    constrained = strata_lgl(spec$constrained, FALSE),
    verbose = FALSE
  )
  st <- strata_scalar(spec$singular_threshold)
  if (!is.null(st)) base_args$singular_threshold <- as.numeric(st)

  started <- Sys.time()
  if (length(extra) > 0) {
    fit <- do.call(admixtools::qpadm, c(base_args, list(target = NULL, return_f4 = TRUE), extra))
  } else {
    fit <- do.call(admixtools::qpwave, base_args)
  }
  elapsed <- as.numeric(difftime(Sys.time(), started, units = "secs"))

  rankdrop <- strata_df(fit$rankdrop)

  # Smallest rank whose overall fit is not rejected at `alpha`.
  min_rank <- NULL
  if (!is.null(fit$rankdrop)) {
    rd <- as.data.frame(fit$rankdrop, stringsAsFactors = FALSE)
    rd <- rd[order(rd$f4rank), , drop = FALSE]
    ok <- which(is.finite(rd$p) & rd$p > alpha)
    if (length(ok) > 0) min_rank <- as.integer(rd$f4rank[[ok[[1]]]])
  }

  list(
    kind = "qpwave",
    left = as.list(left),
    right = as.list(right),
    data_source = resolved$source,
    rankdrop = rankdrop,
    f4 = strata_df(fit$f4),
    alpha = alpha,
    min_rank_not_rejected = min_rank,
    f4_var_rcond = strata_num_or_null(fit$f4_var_rcond),
    f4_var_singular_loadings = strata_df(fit$f4_var_singular_loadings),
    elapsed_seconds = elapsed,
    options = list(
      allsnps = isTRUE(extra$allsnps),
      blgsize = base_args$blgsize,
      fudge = base_args$fudge,
      auto_only = base_args$auto_only,
      constrained = base_args$constrained
    )
  )
}

strata_main(run_qpwave)
