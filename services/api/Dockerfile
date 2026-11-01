# Strata HTTP API: FastAPI on uvicorn. No R here.
#
# Build from the repository root:
#   docker build -f services/api/Dockerfile -t strata-api .
#
# This image deliberately has no R and no ADMIXTOOLS 2: qpAdm jobs are enqueued
# and executed by services/worker, so `qpadm_available()` is False here and
# /health reports the capability as off. That keeps the public-facing image
# small and keeps GPL-3 ADMIXTOOLS 2 out of it.

FROM python:3.12-slim-bookworm AS pybuild

RUN pip install --no-cache-dir build hatchling
WORKDIR /src
COPY services/api/pyproject.toml ./services/api/pyproject.toml
COPY services/api/strata ./services/api/strata
RUN python -m build --wheel --outdir /wheels ./services/api

FROM python:3.12-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="strata-api" \
      org.opencontainers.image.description="Strata HTTP API (FastAPI)" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin strata

COPY --from=pybuild /wheels /tmp/wheels
RUN pip install --no-cache-dir /tmp/wheels/*.whl && rm -rf /tmp/wheels

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STRATA_DERIVED_DIR=/app/data/derived \
    STRATA_EXAMPLES_DIR=/app/data/examples \
    PORT=8000

# Mounted read-only by infra/docker-compose.yml; created so the image also
# starts before any reference data has been built.
RUN mkdir -p /app/data/derived /app/data/examples && chown -R strata:strata /app/data

USER strata
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,os,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health', timeout=4).status==200 else 1)"

# One worker process: the API is I/O bound and the job queue does the heavy
# lifting. Scale with replicas, not with in-process workers.
CMD ["sh", "-c", "exec uvicorn strata.api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
