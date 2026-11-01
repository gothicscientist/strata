"""f-statistics (f2, f3, f4) from allele frequencies, pure NumPy.

Estimators follow Patterson et al. (2012) with unbiased finite-sample corrections, where
``n`` is the number of sampled chromosomes in a population at a SNP:

* f2(A,B)   = (a - b)^2 - a(1-a)/(n_A-1) - b(1-b)/(n_B-1)
* f3(C;A,B) = (c - a)(c - b) - c(1-c)/(n_C-1)
* f4(A,B;C,D) = (a - b)(c - d)                  (unbiased without correction)

Per-SNP values are averaged over SNPs valid for the statistic; standard errors use the
weighted block jackknife (Busing et al. 1999) over contiguous genomic blocks, as in
ADMIXTOOLS. Blocks default to 5 cM when genetic positions are available, otherwise to 5 Mb of
physical position (about 5 cM at the genome-wide average of ~1 cM/Mb). These are used to
cross-check ADMIXTOOLS 2 and for quick diagnostics; formal qpAdm runs go through
``strata.qpadm``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from strata.analysis.types import FStatResult


def assign_blocks(
    chrom: np.ndarray,
    pos: np.ndarray,
    *,
    genpos: np.ndarray | None = None,
    block_size: float | None = None,
) -> np.ndarray:
    """Contiguous block ids. ``genpos`` in Morgans (block_size default 0.05 = 5 cM); otherwise
    physical positions in bp (default 5e6). SNPs must be sorted by chromosome and position."""
    chrom = np.asarray(chrom).astype(str)
    use_gen = genpos is not None and np.any(np.asarray(genpos) > 0)
    coord = np.asarray(genpos if use_gen else pos, dtype=np.float64)
    size = block_size if block_size is not None else (0.05 if use_gen else 5e6)
    blocks = np.empty(chrom.shape[0], dtype=np.int64)
    b = -1
    cur_chrom = None
    start = 0.0
    for i in range(chrom.shape[0]):
        if chrom[i] != cur_chrom or coord[i] - start >= size:
            b += 1
            cur_chrom = chrom[i]
            start = coord[i]
        blocks[i] = b
    return blocks


@dataclass
class FrequencyData:
    """Per-population allele frequencies (of the counted allele) and chromosome counts."""

    populations: list[str]
    freqs: np.ndarray  # (P, m), NaN where no data
    counts: np.ndarray  # (P, m) number of sampled chromosomes
    block_ids: np.ndarray  # (m,)

    def index(self, pop: str) -> int:
        try:
            return self.populations.index(pop)
        except ValueError:
            raise KeyError(f"population {pop!r} not in frequency data") from None

    @classmethod
    def from_genotypes(
        cls,
        G: np.ndarray,
        labels: Sequence[str],
        *,
        block_ids: np.ndarray,
        populations: Sequence[str] | None = None,
        ploidy: np.ndarray | None = None,
    ) -> FrequencyData:
        """``G`` (n_ind, m) dosages 0..2 (NaN or negative = missing). ``ploidy`` per individual:
        2 for diploid calls, 1 for pseudohaploid samples coded 0/2 (one chromosome sampled)."""
        G = np.asarray(G, dtype=np.float64)
        G = np.where((G >= 0) & (G <= 2), G, np.nan)
        labels_a = np.asarray(labels, dtype=object)
        pops = list(populations) if populations is not None else list(dict.fromkeys(labels_a))
        pl = np.full(G.shape[0], 2.0) if ploidy is None else np.asarray(ploidy, dtype=np.float64)
        P, m = len(pops), G.shape[1]
        freqs = np.full((P, m), np.nan)
        counts = np.zeros((P, m))
        for k, pop in enumerate(pops):
            sel = labels_a == pop
            g = G[sel]
            ploid = pl[sel][:, None]
            obs = np.isfinite(g)
            n = np.sum(np.where(obs, ploid, 0.0), axis=0)
            alleles = np.sum(np.where(obs, g / 2.0 * ploid, 0.0), axis=0)
            counts[k] = n
            freqs[k] = np.divide(alleles, n, out=np.full(m, np.nan), where=n > 0)
        return cls(populations=pops, freqs=freqs, counts=counts, block_ids=np.asarray(block_ids))


def block_jackknife(
    values: np.ndarray, valid: np.ndarray, block_ids: np.ndarray
) -> tuple[float, float, int, int]:
    """Mean of per-SNP ``values`` over ``valid`` SNPs with weighted block-jackknife SE.

    Returns (estimate, se, n_snps, n_blocks)."""
    v = np.where(valid, values, 0.0)
    _, inv = np.unique(block_ids, return_inverse=True)
    sums = np.bincount(inv, weights=v)
    cnts = np.bincount(inv, weights=valid.astype(np.float64))
    keep = cnts > 0
    sums, cnts = sums[keep], cnts[keep]
    n = float(cnts.sum())
    g = int(cnts.size)
    if n == 0:
        return float("nan"), float("nan"), 0, 0
    est = float(sums.sum() / n)
    if g < 2:
        return est, float("nan"), int(n), g
    loo = (sums.sum() - sums) / (n - cnts)
    h = n / cnts
    theta_j = g * est - float(np.sum((1.0 - cnts / n) * loo))
    tau = h * est - (h - 1.0) * loo
    finite = h > 1
    var = float(np.sum((tau[finite] - theta_j) ** 2 / (h[finite] - 1.0)) / g)
    return est, float(np.sqrt(var)), int(n), g


def _result(
    stat: str, pops: list[str], vals: np.ndarray, valid: np.ndarray, blocks: np.ndarray
) -> FStatResult:
    est, se, n_snps, n_blocks = block_jackknife(vals, valid, blocks)
    z = est / se if se and np.isfinite(se) and se > 0 else float("nan")
    return FStatResult(
        stat=stat, populations=pops, estimate=est, se=se, z=z, n_snps=n_snps, n_blocks=n_blocks
    )  # type: ignore[arg-type]


def _f2_per_snp(
    data: FrequencyData, i: int, j: int, *, unbiased: bool
) -> tuple[np.ndarray, np.ndarray]:
    a, b = data.freqs[i], data.freqs[j]
    na, nb = data.counts[i], data.counts[j]
    valid = np.isfinite(a) & np.isfinite(b)
    with np.errstate(invalid="ignore", divide="ignore"):
        val = (a - b) ** 2
        if unbiased:
            valid &= (na >= 2) & (nb >= 2)
            val = val - a * (1 - a) / (na - 1) - b * (1 - b) / (nb - 1)
    return np.where(valid, val, 0.0), valid


def f2(data: FrequencyData, a: str, b: str, *, unbiased: bool = True) -> FStatResult:
    val, valid = _f2_per_snp(data, data.index(a), data.index(b), unbiased=unbiased)
    return _result("f2", [a, b], val, valid, data.block_ids)


def f3(data: FrequencyData, c: str, a: str, b: str, *, unbiased: bool = True) -> FStatResult:
    """f3(C; A, B): negative values (z < -3) indicate C is admixed between relatives of A, B."""
    ic, ia, ib = data.index(c), data.index(a), data.index(b)
    pc, pa, pb = data.freqs[ic], data.freqs[ia], data.freqs[ib]
    nc = data.counts[ic]
    valid = np.isfinite(pc) & np.isfinite(pa) & np.isfinite(pb)
    with np.errstate(invalid="ignore", divide="ignore"):
        val = (pc - pa) * (pc - pb)
        if unbiased:
            valid &= nc >= 2
            val = val - pc * (1 - pc) / (nc - 1)
    return _result("f3", [c, a, b], np.where(valid, val, 0.0), valid, data.block_ids)


def f4(data: FrequencyData, a: str, b: str, c: str, d: str) -> FStatResult:
    """f4(A, B; C, D) = E[(a - b)(c - d)]; ~0 if (A,B) and (C,D) form clades."""
    P = [data.freqs[data.index(x)] for x in (a, b, c, d)]
    valid = np.all([np.isfinite(p) for p in P], axis=0)
    with np.errstate(invalid="ignore"):
        val = (P[0] - P[1]) * (P[2] - P[3])
    return _result("f4", [a, b, c, d], np.where(valid, val, 0.0), valid, data.block_ids)


def f2_blocks(data: FrequencyData, *, unbiased: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Per-block mean f2 for all population pairs: array (P, P, n_blocks) and SNP counts per
    block (P, P, n_blocks), analogous to ADMIXTOOLS 2 ``f2_blocks``."""
    P = len(data.populations)
    _, inv = np.unique(data.block_ids, return_inverse=True)
    nb = int(inv.max()) + 1 if inv.size else 0
    out = np.zeros((P, P, nb))
    cnt = np.zeros((P, P, nb))
    for i in range(P):
        for j in range(i + 1, P):
            val, valid = _f2_per_snp(data, i, j, unbiased=unbiased)
            s = np.bincount(inv, weights=val, minlength=nb)
            c = np.bincount(inv, weights=valid.astype(float), minlength=nb)
            m = np.divide(s, c, out=np.full(nb, np.nan), where=c > 0)
            out[i, j] = out[j, i] = m
            cnt[i, j] = cnt[j, i] = c
    return out, cnt
