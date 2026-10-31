#!/usr/bin/env Rscript
# f4-statistics (and D-statistics) via ADMIXTOOLS 2's qpdstat().
#
#   Rscript f4.R spec.json out.json
#
# Spec (JSON object):
#   f2_dir | geno_prefix               as in qpadm.R
#   pop1, pop2, pop3, pop4  [str]      population vectors
#   comb            bool  = true       all combinations of pop1..pop4; if false
#                                      the four vectors must be the same length
#                                      and are zipped row-wise
#   f4mode          bool  = true       false => D-statistics (geno_prefix only)
#   afprod          bool  = true       f2_dir only: compute from allele-freq products
#   unique_only     bool  = true       drop permutation-equivalent quadruples
#   boot            bool|int = false
#   blgsize         float = 0.05       geno_prefix only
#   allsnps, maxmiss, auto_only        geno_prefix only
#   threads         int   = 1
#
# Output: `f4`, one record per quadruple with pop1..pop4, est, se, z, p and
# (genotype input only) n = number of SNPs used.
#
# f4(A, B; C, D) is zero in expectation when the A/B split is unrelated to the
# C/D split. |z| >= 3 is the conventional threshold for rejecting that, which
# corresponds to p ~ 0.0027 two-sided before any multiple-testing correction.

local({
  here <- dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
  source(file.path(here, "common.R"), local = FALSE)
})

run_f4 <- function(spec) {
  resolved <- strata_resolve_data(spec)
  extra <- strata_geno_args(spec, resolved$source)

  pop1 <- strata_chr(strata_require(spec, "pop1"), "pop1")
  pop2 <- strata_chr(strata_require(spec, "pop2"), "pop2")
  pop3 <- strata_chr(strata_require(spec, "pop3"), "pop3")
  pop4 <- strata_chr(strata_require(spec, "pop4"), "pop4")

  comb <- strata_lgl(spec$comb, TRUE)
  if (!comb) {
    lens <- c(length(pop1), length(pop2), length(pop3), length(pop4))
    if (length(unique(lens)) != 1) {
      stop(sprintf(
        "with comb=false, pop1..pop4 must have equal length; got %s",
        paste(lens, collapse = "/")
      ))
    }
  }

  f4mode <- strata_lgl(spec$f4mode, TRUE)
  if (!f4mode && resolved$source != "geno_prefix") {
    stop("f4mode=false (D-statistics) requires 'geno_prefix'; f2 blocks cannot give D-statistics")
  }

  call_args <- c(list(
    data = resolved$data,
    pop1 = pop1, pop2 = pop2, pop3 = pop3, pop4 = pop4,
    comb = comb,
    unique_only = strata_lgl(spec$unique_only, TRUE),
    f4mode = f4mode,
    boot = strata_scalar(spec$boot, FALSE),
    sure = TRUE,
    verbose = FALSE
  ), extra)

  if (resolved$source == "geno_prefix") {
    call_args$blgsize <- strata_num(spec$blgsize, 0.05)
    call_args$auto_only <- strata_lgl(spec$auto_only, TRUE)
  } else {
    call_args$afprod <- strata_lgl(spec$afprod, TRUE)
  }

  started <- Sys.time()
  res <- do.call(admixtools::qpdstat, call_args)
  elapsed <- as.numeric(difftime(Sys.time(), started, units = "secs"))

  list(
    kind = if (f4mode) "f4" else "dstat",
    data_source = resolved$source,
    f4 = strata_df(res),
    n_statistics = nrow(as.data.frame(res)),
    elapsed_seconds = elapsed,
    options = list(
      comb = comb,
      f4mode = f4mode,
      unique_only = call_args$unique_only,
      allsnps = isTRUE(extra$allsnps),
      boot = call_args$boot
    )
  )
}

strata_main(run_f4)
