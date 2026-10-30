"""Align a single sample's genotype calls to a reference SNP panel.

Dosage convention: the number of copies of the panel's counted allele ``SnpPanel.ref``
(EIGENSTRAT .snp column 5 / PLINK A1), so harmonised samples can be merged directly into
EIGENSTRAT/PACKEDANCESTRYMAP reference data. ``counted="alt"`` gives 2 - dosage instead.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from strata.io.types import (
    HarmonizedGenotypes,
    OverlapStats,
    ParseWarning,
    RawGenotypes,
    SnpPanel,
)

_COMP = {"A": "T", "T": "A", "C": "G", "G": "C", "-": "-"}


def complement(alleles: np.ndarray) -> np.ndarray:
    return pd.Series(alleles, dtype=object).map(_COMP).fillna("?").to_numpy(dtype=object)


def is_strand_ambiguous(ref: np.ndarray, alt: np.ndarray) -> np.ndarray:
    pair = pd.Series(ref, dtype=object) + pd.Series(alt, dtype=object)
    return pair.isin(["AT", "TA", "CG", "GC"]).to_numpy()


def _position_keys(chrom: np.ndarray, pos: np.ndarray) -> pd.Index:
    return pd.Index(pd.Series(chrom, dtype=str) + ":" + pd.Series(pos, dtype=np.int64).astype(str))


def harmonize(
    raw: RawGenotypes,
    panel: SnpPanel,
    *,
    counted: Literal["ref", "alt"] = "ref",
    position_fallback: bool = True,
) -> HarmonizedGenotypes:
    warnings: list[ParseWarning] = []
    raw_ids = pd.Index(raw.rsid)
    if not raw_ids.is_unique:
        keep = ~raw_ids.duplicated(keep="first")
        raw_ids = raw_ids[keep]
        raw_rows = np.flatnonzero(keep)
    else:
        raw_rows = np.arange(raw.n)
    idx = raw_ids.get_indexer(pd.Index(panel.rsid))
    idx = np.where(idx >= 0, raw_rows[np.maximum(idx, 0)], -1)
    by_rsid = int(np.sum(idx >= 0))

    by_pos = 0
    same_build = raw.build == panel.build and raw.build != "unknown"
    use_pos = position_fallback and same_build and np.any(idx < 0)
    if position_fallback and not same_build:
        warnings.append(
            ParseWarning(
                code="no_position_fallback",
                message=f"Input build {raw.build} differs from panel build {panel.build}; "
                "matched by rsID only.",
            )
        )
    if use_pos:
        used = np.zeros(raw.n, dtype=bool)
        used[idx[idx >= 0]] = True
        raw_keys = _position_keys(raw.chrom, raw.pos)
        dup = raw_keys.duplicated(keep=False) | used
        cand_rows = np.flatnonzero(~dup)
        cand_keys = raw_keys[cand_rows]
        miss = np.flatnonzero(idx < 0)
        pidx = cand_keys.get_indexer(_position_keys(panel.chrom[miss], panel.pos[miss]))
        hit = pidx >= 0
        idx[miss[hit]] = cand_rows[pidx[hit]]
        by_pos = int(hit.sum())

    matched = idx >= 0
    m = np.flatnonzero(matched)
    a1 = raw.allele1[idx[m]]
    a2 = raw.allele2[idx[m]]
    ref = panel.ref[m]
    alt = panel.alt[m]

    ambiguous = is_strand_ambiguous(ref, alt)
    nocall = (a1 == "-") | (a2 == "-")

    def fits(x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
        return ((x1 == ref) | (x1 == alt)) & ((x2 == ref) | (x2 == alt))

    direct = fits(a1, a2)
    c1, c2 = complement(a1), complement(a2)
    flip = ~direct & fits(c1, c2)
    usable = ~ambiguous & ~nocall & (direct | flip)
    mismatch = ~ambiguous & ~nocall & ~direct & ~flip

    f1 = np.where(flip, c1, a1)
    f2 = np.where(flip, c2, a2)
    d = (f1 == ref).astype(np.float64) + (f2 == ref).astype(np.float64)
    if counted == "alt":
        d = 2.0 - d
    dosage = np.full(panel.n, np.nan)
    dosage[m[usable]] = d[usable]

    n_usable = int(usable.sum())
    n_mismatch = int(mismatch.sum())
    if n_mismatch > 0.01 * max(len(m), 1):
        warnings.append(
            ParseWarning(
                code="allele_mismatch",
                message="More than 1% of matched SNPs have alleles inconsistent with the panel; "
                "check genome build and strand.",
                count=n_mismatch,
            )
        )
    if not set(np.unique(panel.ref[: min(panel.n, 1000)])) & {"A", "C", "G", "T"}:
        warnings.append(
            ParseWarning(code="panel_alleles", message="Panel has no allele information.")
        )
    overlap = OverlapStats(
        n_panel=panel.n,
        n_input=raw.n,
        matched_by_rsid=by_rsid,
        matched_by_position=by_pos,
        n_matched=int(matched.sum()),
        n_strand_flipped=int((flip & usable).sum()),
        n_ambiguous_dropped=int(ambiguous.sum()),
        n_allele_mismatch=n_mismatch,
        n_nocall=int((nocall & ~ambiguous).sum()),
        n_usable=n_usable,
        overlap_fraction=n_usable / panel.n if panel.n else 0.0,
        mismatch_examples=[str(s) for s in panel.rsid[m[mismatch]][:10]],
        position_fallback_used=bool(use_pos),
    )
    return HarmonizedGenotypes(
        panel_name=panel.name,
        build=panel.build,
        counted_allele=counted,
        dosage=dosage,
        overlap=overlap,
        warnings=warnings,
    )
