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


def packed_input(prefix: Path, ind_ids: list[str], work_dir: Path) -> Path:
    """Return a genotype prefix ADMIXTOOLS 2 can read for these individuals.

    AADR v66.p1 ships transposed packed ancestrymap (``TGENO``), which
    ADMIXTOOLS 2.0.10 does not read. When the source is TGENO, the selected
    individuals are rewritten as ordinary ``GENO`` (SNP-major) under
    `work_dir`, keeping every SNP in the original order; the conversion is
    skipped when an up-to-date copy already exists. Other formats pass through.
    """
    from strata.io import read_eigenstrat_dataset, write_eigenstrat_dataset
    from strata.io.eigenstrat import detect_geno_format

    if detect_geno_format(f"{prefix}.geno") != "transposed_packedancestrymap":
        return prefix
    out = work_dir / f"{prefix.name}.f2input"
    stamp = Path(f"{out}.ids")
    wanted = "\n".join(sorted(ind_ids))
    if Path(f"{out}.geno").is_file() and stamp.is_file() and stamp.read_text() == wanted:
        log.info("reusing packed f2 input %s", out)
        return out
    log.info("converting %d individuals from TGENO to GENO -> %s", len(ind_ids), out)
    work_dir.mkdir(parents=True, exist_ok=True)
    ds = read_eigenstrat_dataset(prefix, individuals=ind_ids)
    write_eigenstrat_dataset(out, ds)
    stamp.write_text(wanted)
    return out


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
    work_dir: Path | None = None,
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

    from strata.io.eigenstrat import read_ind

    wanted = {p.group_id for p in populations}
    # samples.parquet merges the HO and 1240K curations; present-day Human
    # Origins individuals have no 1240K genotypes, so keep only the
    # individuals this genotype file actually carries.
    in_file = {r.id for r in read_ind(f"{prefix}.ind")}
    members = [s for s in samples if s.group_id in wanted and s.id in in_file]
    dropped = sum(1 for s in samples if s.group_id in wanted and s.id not in in_file)
    if dropped:
        log.info("%d curated individuals are not in %s.ind and are skipped", dropped, prefix.name)
    if not members:
        raise ValueError("no curated individuals fall in the requested populations")

    # ADMIXTOOLS takes paired inds/pops vectors, which is how several
    # individuals are grouped into one population.
    inds = [s.id for s in members]
    pops = [s.group_id for s in members]
    log.info("extract_f2: %d individuals in %d populations", len(inds), len(set(pops)))

    geno_prefix = packed_input(prefix, inds, work_dir or out_dir.parent / "work")

    spec = ExtractF2Spec(
        geno_prefix=str(geno_prefix),
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
