"""Build the ADMIXTOOLS 2 f2 block cache for the curated panel.

This stage is a thin, auditable wrapper over `strata.qpadm.extract_f2`: the
same code path the worker uses, so the cache the pipeline builds and a cache
built in the worker image are byte-comparable given the same inputs.

An f2 cache fixes the SNP set and every filter for all downstream statistics.
Two caches built with different options give different p-values for the same
model, so the options are pinned in `config.F2` and the resulting
`cache_id` is recorded in the MANIFEST.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import F2, F2Config
from .curate import CuratedPopulation, CuratedSample

log = logging.getLogger(__name__)


@dataclass
class F2Build:
    f2_dir: Path
    pops: list[str]
    n_pops: int
    n_snps: float | None
    n_blocks: float | None
    cache_id: str | None
    options: dict[str, Any]
    result: Any


def build_f2(
    *,
    prefix: Path,
    out_dir: Path,
    populations: list[CuratedPopulation],
    samples: list[CuratedSample],
    config: F2Config = F2,
    overwrite: bool = False,
    timeout: float | None = None,
) -> F2Build:
    """Extract f2 blocks for the curated panel's populations.

    Individuals are passed explicitly alongside their group labels, so the
    grouping in the cache is exactly the curated one — AADR's own `.ind` file
    assigns individuals to groups that curation may have changed (a dropped
    duplicate, a relabelled outlier).

    Args:
        prefix: EIGENSTRAT prefix of the AADR 1240K dataset.
        out_dir: Directory for the cache.
        populations: Curated populations to include.
        samples: Curated individuals; filtered to the given populations.
        config: Pinned extraction options.
        overwrite: Rebuild an existing cache.
        timeout: Seconds for the R process; f2 extraction on a full panel
            takes hours, so this defaults to no limit beyond R's own.

    Raises:
        RuntimeError: ADMIXTOOLS 2 is unavailable, or extraction failed.
    """
    from strata.qpadm import ExtractF2Spec, QpAdmError, extract_f2, qpadm_available

    if not qpadm_available():
        raise RuntimeError(
            "ADMIXTOOLS 2 is not available, so f2 blocks cannot be built. "
            "Run services/worker/r/install_env.sh and set STRATA_RSCRIPT."
        )

    wanted = {p.group_id for p in populations}
    members = [s for s in samples if s.group_id in wanted]
    if not members:
        raise ValueError("no curated individuals fall in the requested populations")

    # ADMIXTOOLS takes paired inds/pops vectors, which is how several
    # individuals are grouped into one population.
    inds = [s.id for s in members]
    pops = [s.group_id for s in members]
    log.info("extract_f2: %d individuals in %d populations", len(inds), len(set(pops)))

    spec = ExtractF2Spec(
        geno_prefix=str(prefix),
        out_dir=str(out_dir),
        inds=inds,
        pops=pops,
        blgsize=config.blgsize,
        maxmiss=config.maxmiss,
        minmaf=config.minmaf,
        auto_only=config.auto_only,
        transitions=config.transitions,
        transversions=config.transversions,
        adjust_pseudohaploid=config.adjust_pseudohaploid,
        afprod=config.afprod,
        fst=config.fst,
        n_cores=config.n_cores,
        overwrite=overwrite,
    )
    try:
        result = extract_f2(spec, timeout=timeout)
    except QpAdmError as exc:
        raise RuntimeError(f"f2 extraction failed: {exc}") from exc

    return F2Build(
        f2_dir=Path(result.f2_dir),
        pops=list(result.pops),
        n_pops=result.n_pops,
        n_snps=result.n_snps,
        n_blocks=result.n_blocks,
        cache_id=result.cache_id,
        options=dict(result.options),
        result=result,
    )
