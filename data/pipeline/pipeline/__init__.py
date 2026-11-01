"""Strata's reproducible AADR reference-data pipeline.

Stages: download -> curate -> pca -> f2 -> manifest. Run with
``python -m pipeline <stage>`` from ``data/pipeline``, or via the Makefile
there. Every stage is idempotent so an interrupted build resumes.

The pipeline needs Harvard Dataverse (for AADR) and, for the ``f2`` stage, a
working ADMIXTOOLS 2 install. Neither is reachable from the development
container, so it is executed by ``.github/workflows/build-reference.yml``.
``pipeline.anno`` and ``pipeline.curate`` are pure and unit-tested against a
small fixture, which is where the version-fragile logic lives.
"""

from __future__ import annotations

from .config import AADR_VERSION, PIPELINE_VERSION, REFERENCE_VERSION, SCHEMA_VERSION

__all__ = ["AADR_VERSION", "PIPELINE_VERSION", "REFERENCE_VERSION", "SCHEMA_VERSION"]
