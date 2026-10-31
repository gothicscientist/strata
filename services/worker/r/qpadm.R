#!/usr/bin/env Rscript
# qpAdm via ADMIXTOOLS 2.
#
#   Rscript qpadm.R spec.json out.json
#
# Spec (JSON object):
#   target          str                target population
#   left            [str]              source populations
#   right           [str]              outgroup / "right" populations
#   f2_dir          str                directory of precomputed f2 blocks  (XOR geno_prefix)
#   geno_prefix     str                EIGENSTRAT/PLINK prefix             (XOR f2_dir)
#   allsnps         bool  = false      geno_prefix only: per-f4 SNP selection
#   maxmiss         float = 0          geno_prefix only: max missingness per SNP
#   blgsize         float = 0.05       jackknife block size in Morgan (>=100 => bp)
#   fudge           float = 1e-4       ridge added to the f4 variance diagonal
#   fudge_twice     bool  = false      match the original qpAdm p-values more closely
#   auto_only       bool  = true       autosomes only
#   poly_only       bool  = false      drop sites with identical allele freqs
#   boot            bool|int = false   block bootstrap instead of jackknife
#   constrained     bool  = false      constrain weights to be non-negative
#   getcov          bool  = true       compute weight standard errors
#   return_f4       bool  = true       include the f4 table
#   singular_threshold float|null      error out below this f4-variance rcond
#   threads         int   = 1
#
# Output: weights, f4, rankdrop, popdrop, the headline fit statistics for the
# full-rank model, and the f4-variance conditioning diagnostics.

local({
  here <- dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
  source(file.path(here, "common.R"), local = FALSE)
})

run_qpadm <- function(spec) {
  target <- strata_scalar(strata_require(spec, "target"))
  left <- strata_chr(strata_require(spec, "left"), "left")
  right <- strata_chr(strata_require(spec, "right"), "right")

  if (length(left) < 1) stop("'left' must contain at least one source population")
  if (length(right) < 2) {
    stop("'right' must contain at least two outgroup populations (qpAdm needs right[1] as the anchor)")
  }
  if (target %in% left) stop("target must not also appear in 'left'")
  if (target %in% right) stop("target must not also appear in 'right'")
  overlap <- intersect(left, right)
  if (length(overlap) > 0) {
    stop(sprintf("populations appear on both sides: %s", paste(overlap, collapse = ", ")))
  }
  if (length(right) <= length(left)) {
    stop(sprintf(
      "qpAdm needs more right populations than left: got %d left and %d right",
      length(left), length(right)
    ))
  }

  resolved <- strata_resolve_data(spec)
  extra <- strata_geno_args(spec, resolved$source)

  call_args <- c(list(
    data = resolved$data,
    left = left,
    right = right,
    target = target,
    fudge = strata_num(spec$fudge, 1e-4),
    fudge_twice = strata_lgl(spec$fudge_twice, FALSE),
    auto_only = strata_lgl(spec$auto_only, TRUE),
    blgsize = strata_num(spec$blgsize, 0.05),
    poly_only = strata_lgl(spec$poly_only, FALSE),
    boot = strata_scalar(spec$boot, FALSE),
    getcov = strata_lgl(spec$getcov, TRUE),
    constrained = strata_lgl(spec$constrained, FALSE),
    return_f4 = strata_lgl(spec$return_f4, TRUE),
    verbose = FALSE
  ), extra)

  st <- strata_scalar(spec$singular_threshold)
  if (!is.null(st)) call_args$singular_threshold <- as.numeric(st)

  started <- Sys.time()
  fit <- do.call(admixtools::qpadm, call_args)
  elapsed <- as.numeric(difftime(Sys.time(), started, units = "secs"))

  # Headline statistics come from the full-rank row of the rank-drop table:
  # rank = (number of sources - 1) is the model qpAdm is actually fitting.
  full_rank <- length(left) - 1L
  headline <- list(p = NULL, chisq = NULL, dof = NULL, f4rank = full_rank)
  if (!is.null(fit$rankdrop)) {
    rd <- as.data.frame(fit$rankdrop, stringsAsFactors = FALSE)
    row <- rd[rd$f4rank == full_rank, , drop = FALSE]
    if (nrow(row) >= 1) {
      headline$p <- strata_num_or_null(row$p[[1]])
      headline$chisq <- strata_num_or_null(row$chisq[[1]])
      headline$dof <- strata_num_or_null(row$dof[[1]])
    }
  }

  list(
    kind = "qpadm",
    target = target,
    left = as.list(left),
    right = as.list(right),
    data_source = resolved$source,
    weights = strata_df(fit$weights),
    f4 = strata_df(fit$f4),
    rankdrop = strata_df(fit$rankdrop),
    popdrop = strata_df(fit$popdrop),
    p = headline$p,
    chisq = headline$chisq,
    dof = headline$dof,
    f4rank = headline$f4rank,
    f4_var_rcond = strata_num_or_null(fit$f4_var_rcond),
    f4_var_singular_loadings = strata_df(fit$f4_var_singular_loadings),
    elapsed_seconds = elapsed,
    options = list(
      allsnps = isTRUE(extra$allsnps),
      maxmiss = if (is.null(extra$maxmiss)) NULL else extra$maxmiss,
      blgsize = call_args$blgsize,
      fudge = call_args$fudge,
      fudge_twice = call_args$fudge_twice,
      auto_only = call_args$auto_only,
      poly_only = call_args$poly_only,
      constrained = call_args$constrained,
      boot = call_args$boot
    )
  )
}

strata_main(run_qpadm)
