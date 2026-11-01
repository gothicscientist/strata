# Strata computational worker: Python + R 4.5 + ADMIXTOOLS 2.
#
# Build from the repository root:
#   docker build -f services/worker/Dockerfile -t strata-worker .
#
# Runs the job queue consumer. Every f-statistic job shells out to
# services/worker/r/*.R, so this image is the only place R is needed.
#
# Licensing: ADMIXTOOLS 2 is GPL-3. Distributing this image distributes
# ADMIXTOOLS 2, so the image must carry its source offer; see
# docs/DATA_PROVENANCE.md.

# --------------------------------------------------------------------------
# stage 1: build the R environment and compile ADMIXTOOLS 2
# --------------------------------------------------------------------------
FROM mambaorg/micromamba:2.3.0-debian12-slim AS rbuild

# uqrmaie1/admixtools, DESCRIPTION Version: 2.0.10. Pinned by commit so the
# f-statistics this image produces are reproducible.
ARG ADMIXTOOLS2_COMMIT=472d04e98ac8aa70e5c9cbe65722c7e5dfbe8200
ARG ADMIXTOOLS2_REPO=https://github.com/uqrmaie1/admixtools

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# CRAN is deliberately not used: conda-forge pins give a reproducible solve and
# the build environments here cannot reach CRAN. r-cubelyr lives in
# conda-forge's noarch subdir; micromamba resolves it from the same channel.
# gxx/libgomp satisfy ADMIXTOOLS 2's "SystemRequirements: C++17, OpenMP".
RUN micromamba create -y -p /opt/strata-r -c conda-forge \
      "r-base>=4.4,<4.6" \
      r-abind r-cli r-crayon r-cubelyr r-data.tree r-digest r-doparallel \
      "r-dplyr>=1.1.0" r-foreach r-furrr r-future r-ggplot2 "r-igraph>=2.1.0" \
      r-jsonlite r-lobstr r-magrittr r-parallelly r-pgenlibr r-quadprog \
      r-purrr r-rcpp r-rcpparmadillo r-readr r-rlang r-stringi r-stringr \
      "r-tibble>=3.1.0" "r-tidyr>=1.0.0" r-genio r-pracma \
      make "gxx_linux-64>=12" libgomp \
 && micromamba clean --all --yes

ENV PATH=/opt/strata-r/bin:$PATH

RUN git clone --quiet "${ADMIXTOOLS2_REPO}" /tmp/admixtools \
 && git -C /tmp/admixtools checkout --quiet "${ADMIXTOOLS2_COMMIT}" \
 && git -C /tmp/admixtools rev-parse HEAD > /opt/strata-r/ADMIXTOOLS2_COMMIT \
 && MAKEFLAGS="-j2" R CMD INSTALL --no-docs --no-help /tmp/admixtools \
 && rm -rf /tmp/admixtools

# Fail the build rather than ship an image whose f-statistics do not work.
RUN Rscript -e 'suppressMessages(library(admixtools)); \
      left  <- c("Altai_Neanderthal.DG", "Vindija.DG"); \
      right <- c("Chimp.REF", "Mbuti.DG", "Russia_Ust_Ishim.DG", "Switzerland_Bichon.SG"); \
      fit <- qpadm(example_f2_blocks, left, right, "Denisova.DG", verbose = FALSE); \
      stopifnot(nrow(fit$weights) == 2L, "p" %in% names(fit$rankdrop)); \
      cat("admixtools", as.character(packageVersion("admixtools")), "OK\n")'

# Record the exact solve for provenance and /health.
RUN Rscript -e 'pkgs <- c("admixtools","abind","cli","crayon","cubelyr","data.tree", \
      "digest","doParallel","dplyr","foreach","furrr","future","ggplot2","igraph", \
      "jsonlite","lobstr","magrittr","parallelly","pgenlibr","quadprog","purrr", \
      "Rcpp","RcppArmadillo","readr","rlang","stringi","stringr","tibble","tidyr","genio"); \
      cat(R.version.string, "\n"); \
      for (p in pkgs) cat(sprintf("%-16s %s\n", p, as.character(packageVersion(p))))' \
      > /opt/strata-r/strata-r-versions.txt

# Drop the compiler toolchain from the layer that gets copied forward.
RUN micromamba remove -y -p /opt/strata-r gxx_linux-64 make || true \
 && micromamba clean --all --yes \
 && find /opt/strata-r -name '*.a' -delete \
 && rm -rf /opt/strata-r/conda-meta/pkgs /opt/strata-r/share/doc

# --------------------------------------------------------------------------
# stage 2: build the Python wheel
# --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS pybuild

RUN pip install --no-cache-dir build hatchling
WORKDIR /src
COPY services/api/pyproject.toml ./services/api/pyproject.toml
COPY services/api/strata ./services/api/strata
RUN python -m build --wheel --outdir /wheels ./services/api

# --------------------------------------------------------------------------
# stage 3: runtime
# --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="strata-worker" \
      org.opencontainers.image.description="Strata f-statistics worker (Python + R + ADMIXTOOLS 2)" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later AND GPL-3.0-only"

# libgomp is needed at runtime by RcppArmadillo's OpenMP kernels even though
# the compiler is gone; the conda env ships its own, but the loader finds the
# system one first for the R binary's own links.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin strata

COPY --from=rbuild /opt/strata-r /opt/strata-r
COPY --from=pybuild /wheels /tmp/wheels
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels

WORKDIR /app
# The R wrapper scripts are read at runtime, not installed into the wheel.
COPY --chown=root:root services/worker/r /app/services/worker/r
RUN chmod -R a+rX /app/services/worker/r

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/strata-r/bin:$PATH \
    STRATA_RSCRIPT=/opt/strata-r/bin/Rscript \
    STRATA_R_DIR=/app/services/worker/r \
    STRATA_DERIVED_DIR=/app/data/derived \
    STRATA_QPADM_TIMEOUT=3600 \
    OMP_NUM_THREADS=1

# The same self-contained image serves the API and bounded queue jobs on Azure.
# No downloads or writable reference volume are needed at startup.
COPY data/derived /app/data/derived
COPY data/examples /app/data/examples
COPY docs/methods /app/docs/methods
COPY data/pipeline/pipeline /app/data/pipeline/pipeline
COPY LICENSE /app/LICENSE
ENV PYTHONPATH=/app/data/pipeline \
    STRATA_DATA_DIR=/app/data \
    STRATA_EXAMPLES_DIR=/app/data/examples \
    STRATA_METHODS_DIR=/app/docs/methods \
    STRATA_F2_DIR=/app/data/derived/f2/strata-ref-v1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
RUN python -m pipeline --root /app fetch-f2 \
 && python -m pipeline --root /app verify

# infra/docker-compose.yml mounts data/derived here read-only. Create it so the
# image also runs standalone, before any reference data exists.
RUN mkdir -p /app/data/derived && chown -R strata:strata /app/data

USER strata

# Liveness: the bridge resolves and ADMIXTOOLS answers.
HEALTHCHECK --interval=60s --timeout=120s --start-period=30s --retries=3 \
  CMD python -c "import sys; from strata.qpadm import qpadm_available; sys.exit(0 if qpadm_available() else 1)"

ENTRYPOINT ["python", "-m", "strata.jobs.worker"]
