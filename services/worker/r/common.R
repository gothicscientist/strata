# Shared helpers for Strata's ADMIXTOOLS 2 wrapper scripts.
#
# Every wrapper follows the same contract:
#   Rscript <script>.R <spec.json> <out.json>
# The spec is a JSON object; the output is a JSON object that always has an
# "ok" field. On success the payload fields are siblings of "ok"; on failure
# "error" holds a structured description. The process exit code is 0 on
# success and 1 on failure, but out.json is written in both cases so the
# Python caller never has to parse stderr.
#
# Nothing here prints genotype data. ADMIXTOOLS progress chatter goes to
# stderr only (captured by the caller for diagnostics), never into the result.

suppressWarnings(suppressMessages({
  library(jsonlite)
}))

STRATA_R_CONTRACT <- "1"

# Read the spec file and return it as a plain list.
strata_read_spec <- function(path) {
  if (!file.exists(path)) stop(sprintf("spec file not found: %s", path))
  jsonlite::fromJSON(path, simplifyVector = TRUE, simplifyDataFrame = FALSE)
}

strata_require <- function(spec, field) {
  v <- spec[[field]]
  if (is.null(v)) stop(sprintf("missing required spec field '%s'", field))
  v
}

# Spec fields are JSON, so scalars may arrive as length-1 vectors or lists.
strata_chr <- function(x, field = "value") {
  if (is.null(x)) return(character(0))
  out <- as.character(unlist(x, use.names = FALSE))
  if (anyNA(out)) stop(sprintf("field '%s' contains null entries", field))
  out
}

strata_scalar <- function(x, default = NULL) {
  if (is.null(x)) return(default)
  x <- unlist(x, use.names = FALSE)
  if (length(x) == 0) return(default)
  x[[1]]
}

strata_lgl <- function(x, default) as.logical(strata_scalar(x, default))
strata_num <- function(x, default) as.numeric(strata_scalar(x, default))
strata_int <- function(x, default) as.integer(strata_scalar(x, default))

# Resolve the `data` argument of qpadm()/qpwave()/qpdstat(): either a
# directory of precomputed f2 blocks or a genotype file prefix.
strata_resolve_data <- function(spec) {
  f2_dir <- strata_scalar(spec$f2_dir)
  geno_prefix <- strata_scalar(spec$geno_prefix)
  if (!is.null(f2_dir) && !is.null(geno_prefix)) {
    stop("specify exactly one of 'f2_dir' or 'geno_prefix', not both")
  }
  if (!is.null(f2_dir)) {
    if (!dir.exists(f2_dir)) stop(sprintf("f2_dir does not exist: %s", f2_dir))
    return(list(data = f2_dir, source = "f2_dir", path = f2_dir))
  }
  if (!is.null(geno_prefix)) {
    # EIGENSTRAT (.geno/.snp/.ind), PACKEDANCESTRYMAP, or PLINK (.bed/.bim/.fam)
    found <- any(file.exists(paste0(geno_prefix, c(
      ".geno", ".bed", ".pgen", ".vcf", ".vcf.gz"
    ))))
    if (!found) {
      stop(sprintf("no genotype files found for prefix: %s", geno_prefix))
    }
    return(list(data = geno_prefix, source = "geno_prefix", path = geno_prefix))
  }
  stop("spec must contain either 'f2_dir' or 'geno_prefix'")
}

# Arguments that only make sense when reading genotypes directly; passed to
# qpadm()'s `...` -> f4blockdat_from_geno(). Silently dropped for f2_dir
# input because extract_f2() has already applied them.
strata_geno_args <- function(spec, source) {
  if (source != "geno_prefix") return(list())
  out <- list()
  if (!is.null(spec$allsnps)) out$allsnps <- strata_lgl(spec$allsnps, FALSE)
  if (!is.null(spec$maxmiss)) out$maxmiss <- strata_num(spec$maxmiss, 0)
  if (!is.null(spec$minmaf)) out$minmaf <- strata_num(spec$minmaf, 0)
  if (!is.null(spec$maxmaf)) out$maxmaf <- strata_num(spec$maxmaf, 0.5)
  if (!is.null(spec$transitions)) out$transitions <- strata_lgl(spec$transitions, TRUE)
  if (!is.null(spec$transversions)) out$transversions <- strata_lgl(spec$transversions, TRUE)
  if (!is.null(spec$adjust_pseudohaploid)) {
    out$adjust_pseudohaploid <- strata_lgl(spec$adjust_pseudohaploid, TRUE)
  }
  out
}

# Convert a data frame / tibble to a list of row records with NaN and Inf
# turned into JSON null, so pydantic sees Optional[float] rather than a string.
strata_df <- function(df) {
  if (is.null(df)) return(NULL)
  df <- as.data.frame(df, stringsAsFactors = FALSE)
  if (nrow(df) == 0) return(list())
  for (nm in names(df)) {
    col <- df[[nm]]
    if (is.list(col)) {
      df[[nm]] <- vapply(col, function(x) paste(as.character(x), collapse = ","), character(1))
    } else if (is.numeric(col)) {
      col[!is.finite(col)] <- NA_real_
      df[[nm]] <- col
    } else if (is.factor(col)) {
      df[[nm]] <- as.character(col)
    }
  }
  # digits = NA keeps full double precision; dataframe = "rows" gives records.
  parsed <- jsonlite::fromJSON(
    jsonlite::toJSON(df, dataframe = "rows", na = "null", digits = NA, auto_unbox = TRUE),
    simplifyVector = FALSE
  )
  parsed
}

strata_num_or_null <- function(x) {
  x <- strata_scalar(x)
  if (is.null(x) || !is.numeric(x) || !is.finite(x)) return(NULL)
  as.numeric(x)
}

# Provenance block stamped onto every result.
strata_provenance <- function(extra = list()) {
  v <- tryCatch(as.character(utils::packageVersion("admixtools")), error = function(e) NA_character_)
  base <- list(
    admixtools_version = v,
    r_version = paste(R.version$major, R.version$minor, sep = "."),
    r_version_string = R.version.string,
    platform = R.version$platform,
    contract = STRATA_R_CONTRACT,
    timestamp_utc = format(as.POSIXlt(Sys.time(), tz = "UTC"), "%Y-%m-%dT%H:%M:%SZ")
  )
  c(base, extra)
}

strata_write <- function(obj, path) {
  json <- jsonlite::toJSON(obj, auto_unbox = TRUE, na = "null", null = "null", digits = NA)
  # Write via a temp file in the same directory so the caller never observes
  # a half-written result.
  tmp <- paste0(path, ".partial")
  writeLines(json, tmp, useBytes = TRUE)
  file.rename(tmp, path)
  invisible(path)
}

strata_fail <- function(path, cond, kind = "error", context = NULL) {
  msg <- if (inherits(cond, "condition")) conditionMessage(cond) else as.character(cond)
  call <- NULL
  if (inherits(cond, "condition") && !is.null(conditionCall(cond))) {
    call <- paste(deparse(conditionCall(cond)), collapse = " ")
  }
  strata_write(list(
    ok = FALSE,
    error = list(
      kind = kind,
      message = msg,
      r_call = call,
      context = context
    ),
    provenance = strata_provenance()
  ), path)
  invisible(NULL)
}

# Entry point used by every wrapper. `fn(spec)` must return a named list of
# payload fields. Errors are captured into the output file.
strata_main <- function(fn, args = commandArgs(trailingOnly = TRUE)) {
  if (length(args) < 2) {
    cat("usage: Rscript <script>.R <spec.json> <out.json>\n", file = stderr())
    quit(status = 2, save = "no")
  }
  spec_path <- args[[1]]
  out_path <- args[[2]]

  spec <- tryCatch(strata_read_spec(spec_path), error = function(e) e)
  if (inherits(spec, "error")) {
    strata_fail(out_path, spec, kind = "spec_error")
    quit(status = 1, save = "no")
  }

  if (!requireNamespace("admixtools", quietly = TRUE)) {
    strata_fail(
      out_path,
      "the 'admixtools' R package is not installed; run services/worker/r/install_env.sh",
      kind = "dependency_missing"
    )
    quit(status = 1, save = "no")
  }

  threads <- strata_int(spec$threads, 1L)
  if (!is.na(threads) && threads > 0) {
    Sys.setenv(OMP_NUM_THREADS = threads)
    options(mc.cores = threads)
  }

  res <- tryCatch(
    withCallingHandlers(
      fn(spec),
      warning = function(w) {
        cat(sprintf("[warn] %s\n", conditionMessage(w)), file = stderr())
        invokeRestart("muffleWarning")
      }
    ),
    error = function(e) e
  )
  if (inherits(res, "error")) {
    strata_fail(out_path, res, kind = "analysis_error")
    quit(status = 1, save = "no")
  }

  res$ok <- TRUE
  if (is.null(res$provenance)) res$provenance <- strata_provenance()
  strata_write(res, out_path)
  quit(status = 0, save = "no")
}
