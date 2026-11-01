#!/usr/bin/env Rscript
# Rotating qpAdm: enumerate every way of splitting a candidate pool into
# left (sources) and right (outgroups), fit each model, rank the results.
#
#   Rscript qpadm_rotate.R spec.json out.json
#
# Spec (JSON object):
#   target          str                target population
#   leftright       [str]              pool rotated between left and right
#   rightfix        [str]  = []        populations pinned to the right in every model
#   f2_dir | geno_prefix               as in qpadm.R
#   max_sources     int    = null      only keep models with <= this many sources
#   min_sources     int    = 1
#   max_models      int    = 400       hard cap; error if enumeration exceeds it
#   full_results    bool   = true      include weights per model
#   allsnps, maxmiss, blgsize, fudge, auto_only, poly_only, boot, constrained
#   threads         int    = 1
#
# Output: `models`, one record per fitted model with left/right, f4rank, dof,
# chisq, p, feasible, f4_var_rcond, and (when full_results) weights; sorted by
# descending p so the best-fitting models come first.
#
# Note on multiple testing: rotation fits many models on the same data, so the
# p-values are NOT independent and must not be read as if a single hypothesis
# had been tested. `n_models_tested` is reported so the caller can say so.

local({
  here <- dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1]))
  source(file.path(here, "common.R"), local = FALSE)
})

run_qpadm_rotate <- function(spec) {
  target <- strata_scalar(strata_require(spec, "target"))
  leftright <- strata_chr(strata_require(spec, "leftright"), "leftright")
  rightfix <- strata_chr(spec$rightfix, "rightfix")

  if (length(leftright) < 2) stop("'leftright' must contain at least two populations")
  if (anyDuplicated(leftright)) stop("'leftright' contains duplicates")
  if (target %in% leftright) stop("target must not appear in 'leftright'")
  if (target %in% rightfix) stop("target must not appear in 'rightfix'")
  clash <- intersect(leftright, rightfix)
  if (length(clash) > 0) {
    stop(sprintf("populations in both 'leftright' and 'rightfix': %s", paste(clash, collapse = ", ")))
  }

  resolved <- strata_resolve_data(spec)
  extra <- strata_geno_args(spec, resolved$source)

  min_sources <- strata_int(spec$min_sources, 1L)
  max_sources <- strata_int(spec$max_sources, NA_integer_)
  max_models <- strata_int(spec$max_models, 400L)
  full_results <- strata_lgl(spec$full_results, TRUE)

  models <- admixtools::rotate_models(leftright, target = target, rightfix = rightfix)
  models <- as.data.frame(models, stringsAsFactors = FALSE)
  n_enumerated <- nrow(models)

  nleft <- vapply(models$left, length, integer(1))
  keep <- nleft >= min_sources
  if (!is.na(max_sources)) keep <- keep & nleft <= max_sources
  models <- models[keep, , drop = FALSE]
  if (nrow(models) == 0) {
    stop(sprintf(
      "no models left after filtering (enumerated %d, min_sources=%d, max_sources=%s)",
      n_enumerated, min_sources, if (is.na(max_sources)) "none" else max_sources
    ))
  }
  if (nrow(models) > max_models) {
    stop(sprintf(
      paste0("rotation would fit %d models, above max_models=%d; ",
             "shrink 'leftright', set 'max_sources', or raise 'max_models'"),
      nrow(models), max_models
    ))
  }

  # rotate_models() already puts the target into each model's `target` column;
  # qpadm_multi() unions it onto `left` internally.
  model_list <- list(
    left = unname(lapply(models$left, as.character)),
    right = unname(lapply(models$right, as.character)),
    target = rep(target, nrow(models))
  )

  fit_args <- c(list(
    data = resolved$data,
    models = model_list,
    full_results = TRUE,
    verbose = FALSE,
    fudge = strata_num(spec$fudge, 1e-4),
    auto_only = strata_lgl(spec$auto_only, TRUE),
    blgsize = strata_num(spec$blgsize, 0.05),
    poly_only = strata_lgl(spec$poly_only, FALSE),
    boot = strata_scalar(spec$boot, FALSE),
    constrained = strata_lgl(spec$constrained, FALSE),
    getcov = TRUE,
    return_f4 = FALSE
  ), extra)
  if (resolved$source == "geno_prefix") {
    fit_args$allsnps <- isTRUE(extra$allsnps)
  }

  started <- Sys.time()
  fits <- do.call(admixtools::qpadm_multi, fit_args)
  elapsed <- as.numeric(difftime(Sys.time(), started, units = "secs"))

  out <- vector("list", length(fits))
  for (i in seq_along(fits)) {
    fit <- fits[[i]]
    left_i <- as.character(models$left[[i]])
    right_i <- as.character(models$right[[i]])
    full_rank <- length(left_i) - 1L

    p <- NULL; chisq <- NULL; dof <- NULL
    if (!is.null(fit$rankdrop)) {
      rd <- as.data.frame(fit$rankdrop, stringsAsFactors = FALSE)
      row <- rd[rd$f4rank == full_rank, , drop = FALSE]
      if (nrow(row) == 0) row <- rd[1, , drop = FALSE]
      if (nrow(row) >= 1) {
        p <- strata_num_or_null(row$p[[1]])
        chisq <- strata_num_or_null(row$chisq[[1]])
        dof <- strata_num_or_null(row$dof[[1]])
      }
    }
    feasible <- NA
    if (!is.null(fit$weights)) {
      w <- as.numeric(as.data.frame(fit$weights)$weight)
      feasible <- if (length(w) == 0 || anyNA(w)) NA else all(w >= 0 & w <= 1)
    }

    rec <- list(
      model_index = i,
      left = as.list(left_i),
      right = as.list(right_i),
      n_sources = length(left_i),
      f4rank = full_rank,
      p = p,
      chisq = chisq,
      dof = dof,
      feasible = feasible,
      f4_var_rcond = strata_num_or_null(fit$f4_var_rcond)
    )
    if (full_results) rec$weights <- strata_df(fit$weights)
    out[[i]] <- rec
  }

  # Rank by p-value descending (best fit first); NA p-values last.
  pv <- vapply(out, function(r) if (is.null(r$p)) -Inf else r$p, numeric(1))
  out <- out[order(pv, decreasing = TRUE)]
  for (i in seq_along(out)) out[[i]]$rank <- i

  list(
    kind = "qpadm_rotate",
    target = target,
    leftright = as.list(leftright),
    rightfix = as.list(rightfix),
    data_source = resolved$source,
    n_models_enumerated = n_enumerated,
    n_models_tested = length(out),
    models = out,
    elapsed_seconds = elapsed,
    options = list(
      min_sources = min_sources,
      max_sources = if (is.na(max_sources)) NULL else max_sources,
      allsnps = isTRUE(extra$allsnps),
      blgsize = fit_args$blgsize,
      fudge = fit_args$fudge,
      constrained = fit_args$constrained
    )
  )
}

strata_main(run_qpadm_rotate)
