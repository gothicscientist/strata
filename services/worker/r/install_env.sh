#!/usr/bin/env bash
# Build the R environment that Strata's f-statistics worker needs:
# R 4.5 + ADMIXTOOLS 2 + jsonlite, installed from conda-forge via micromamba.
#
#   services/worker/r/install_env.sh [PREFIX]
#
# PREFIX defaults to /opt/strata-r, falling back to $HOME/strata-r if /opt is
# not writable. On success the script prints the path to Rscript; export it as
# STRATA_RSCRIPT for strata.qpadm to pick up:
#
#   export STRATA_RSCRIPT="$(services/worker/r/install_env.sh)"
#
# Why conda-forge and not CRAN: the build and CI environments reach
# conda.anaconda.org but not cran.r-project.org, and conda-forge pins give
# byte-reproducible dependency sets. Two packages are not on conda-forge's
# linux-64 subdir and come from source:
#   * cubelyr   -> conda-forge noarch (r-cubelyr), so still a package install
#   * admixtools -> GitHub, pinned to ADMIXTOOLS2_COMMIT below
#
# ADMIXTOOLS 2 is GPL-3. See docs/DATA_PROVENANCE.md.

set -euo pipefail

# --- pins -------------------------------------------------------------------
MICROMAMBA_VERSION="${MICROMAMBA_VERSION:-2.10.0}"
MICROMAMBA_BUILD="${MICROMAMBA_BUILD:-0}"
# uqrmaie1/admixtools, version 2.0.10
ADMIXTOOLS2_COMMIT="${ADMIXTOOLS2_COMMIT:-472d04e98ac8aa70e5c9cbe65722c7e5dfbe8200}"
ADMIXTOOLS2_REPO="${ADMIXTOOLS2_REPO:-https://github.com/uqrmaie1/admixtools}"
R_VERSION_SPEC="${R_VERSION_SPEC:-r-base>=4.4,<4.6}"

CONDA_CHANNEL="${CONDA_CHANNEL:-https://conda.anaconda.org/conda-forge}"

# ADMIXTOOLS 2 DESCRIPTION Imports, all available on conda-forge.
# Versions below are the ones this pin set resolved to on linux-64,
# recorded by install_env.sh --versions (see VERSIONS.md next to this file).
R_DEPS=(
  r-abind r-cli r-crayon r-cubelyr r-data.tree r-digest r-doparallel
  "r-dplyr>=1.1.0" r-foreach r-furrr r-future r-ggplot2 "r-igraph>=2.1.0"
  r-jsonlite r-lobstr r-magrittr r-parallelly r-pgenlibr r-quadprog r-purrr
  r-rcpp r-rcpparmadillo r-readr r-rlang r-stringi r-stringr "r-tibble>=3.1.0"
  "r-tidyr>=1.0.0"
)
# Suggests that Strata's own code paths use: genio reads EIGENSTRAT/PLINK,
# testthat runs ADMIXTOOLS 2's own suite, pracma is used by a few qpgraph paths.
R_DEPS_EXTRA=(r-genio r-testthat r-pracma r-withr)
# Toolchain for compiling the admixtools C++ (Rcpp/RcppArmadillo, C++17, OpenMP).
BUILD_DEPS=(make "gxx_linux-64>=12" "libgomp")

# --- prefix selection -------------------------------------------------------
PREFIX="${1:-}"
if [[ -z "${PREFIX}" ]]; then
  if [[ -w /opt ]] || mkdir -p /opt 2>/dev/null; then
    PREFIX=/opt/strata-r
  else
    PREFIX="${HOME}/strata-r"
  fi
fi
MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-${PREFIX}-root}"
export MAMBA_ROOT_PREFIX

log() { printf '[install_env] %s\n' "$*" >&2; }

# --- micromamba -------------------------------------------------------------
# Prefer an existing micromamba; otherwise fetch the conda-forge package
# tarball and extract just the static binary (no installer script is run).
MICROMAMBA="$(command -v micromamba || true)"
if [[ -z "${MICROMAMBA}" ]]; then
  MM_DIR="$(mktemp -d)"
  log "downloading micromamba ${MICROMAMBA_VERSION}"
  curl -fsSL \
    "${CONDA_CHANNEL}/linux-64/micromamba-${MICROMAMBA_VERSION}-${MICROMAMBA_BUILD}.tar.bz2" \
    -o "${MM_DIR}/micromamba.tar.bz2"
  tar -xjf "${MM_DIR}/micromamba.tar.bz2" -C "${MM_DIR}" bin/micromamba
  MICROMAMBA="${MM_DIR}/bin/micromamba"
  chmod +x "${MICROMAMBA}"
fi
log "micromamba: $(${MICROMAMBA} --version)"

# --- R environment ----------------------------------------------------------
log "creating R environment at ${PREFIX}"
"${MICROMAMBA}" create -y -p "${PREFIX}" -c conda-forge --no-rc \
  "${R_VERSION_SPEC}" "${R_DEPS[@]}" "${R_DEPS_EXTRA[@]}" "${BUILD_DEPS[@]}" >&2

export PATH="${PREFIX}/bin:${PATH}"
RSCRIPT="${PREFIX}/bin/Rscript"
log "R: $("${RSCRIPT}" -e 'cat(R.version.string)')"

# --- ADMIXTOOLS 2 -----------------------------------------------------------
# Installed from a pinned commit so the f-statistics are reproducible. This
# compiles the package's C++ sources with the conda toolchain above.
SRC_DIR="${ADMIXTOOLS2_SRC:-}"
if [[ -z "${SRC_DIR}" ]]; then
  SRC_DIR="$(mktemp -d)/admixtools"
  log "cloning ${ADMIXTOOLS2_REPO} @ ${ADMIXTOOLS2_COMMIT}"
  git clone --quiet "${ADMIXTOOLS2_REPO}" "${SRC_DIR}"
  git -C "${SRC_DIR}" checkout --quiet "${ADMIXTOOLS2_COMMIT}"
else
  log "using existing source tree ${SRC_DIR}"
fi

ACTUAL_COMMIT="$(git -C "${SRC_DIR}" rev-parse HEAD)"
if [[ "${ACTUAL_COMMIT}" != "${ADMIXTOOLS2_COMMIT}" ]]; then
  log "WARNING: source tree is at ${ACTUAL_COMMIT}, expected ${ADMIXTOOLS2_COMMIT}"
fi

log "installing admixtools (R CMD INSTALL)"
MAKEFLAGS="-j$(nproc 2>/dev/null || echo 2)" \
  "${PREFIX}/bin/R" CMD INSTALL --no-docs --no-help "${SRC_DIR}" >&2

# --- verify -----------------------------------------------------------------
"${RSCRIPT}" -e '
  suppressMessages(library(admixtools))
  suppressMessages(library(jsonlite))
  stopifnot(exists("qpadm", where = asNamespace("admixtools")))
  cat("admixtools", as.character(packageVersion("admixtools")), "\n", file = stderr())
  # Smoke test on the f2 blocks bundled with the package.
  left  <- c("Altai_Neanderthal.DG", "Vindija.DG")
  right <- c("Chimp.REF", "Mbuti.DG", "Russia_Ust_Ishim.DG", "Switzerland_Bichon.SG")
  fit <- qpadm(example_f2_blocks, left, right, "Denisova.DG", verbose = FALSE)
  stopifnot(nrow(fit$weights) == 2L, "p" %in% names(fit$rankdrop))
  cat("smoke test OK\n", file = stderr())
' >&2

log "writing version manifest"
"${RSCRIPT}" -e '
  pkgs <- c("admixtools", "abind", "cli", "crayon", "cubelyr", "data.tree",
            "digest", "doParallel", "dplyr", "foreach", "furrr", "future",
            "ggplot2", "igraph", "jsonlite", "lobstr", "magrittr", "parallelly",
            "pgenlibr", "quadprog", "purrr", "Rcpp", "RcppArmadillo", "readr",
            "rlang", "stringi", "stringr", "tibble", "tidyr", "genio")
  cat(R.version.string, "\n")
  for (p in pkgs) {
    v <- tryCatch(as.character(packageVersion(p)), error = function(e) "MISSING")
    cat(sprintf("%-16s %s\n", p, v))
  }
' > "${PREFIX}/strata-r-versions.txt"

log "done. STRATA_RSCRIPT=${RSCRIPT}"
echo "${RSCRIPT}"
