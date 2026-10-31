"""f-statistics tests on SYNTHETIC msprime data (tree ((A,B),C),O; X = 0.3 A + 0.7 B)."""

from __future__ import annotations

import numpy as np
import pytest

from strata.analysis import fstats


@pytest.fixture(scope="module")
def freq(sim):
    blocks = fstats.assign_blocks(sim.chrom, sim.pos, block_size=100_000)
    return fstats.FrequencyData.from_genotypes(sim.G, sim.labels, block_ids=blocks)


def test_assign_blocks():
    chrom = np.array(["1"] * 5 + ["2"] * 3)
    pos = np.array([1, 10, 20, 31, 45, 5, 6, 100])
    b = fstats.assign_blocks(chrom, pos, block_size=20)
    np.testing.assert_array_equal(b, [0, 0, 0, 1, 1, 2, 2, 3])
    gen = np.array([0.0, 0.01, 0.06, 0.07, 0.2, 0.0, 0.0, 0.0])
    b2 = fstats.assign_blocks(chrom, pos, genpos=gen)
    np.testing.assert_array_equal(b2, [0, 0, 1, 1, 2, 3, 3, 3])


def test_jackknife_matches_plain_jackknife_for_equal_blocks():
    rng = np.random.default_rng(0)
    vals = rng.normal(1.0, 1.0, 1000)
    blocks = np.repeat(np.arange(50), 20)
    est, se, n, g = fstats.block_jackknife(vals, np.ones(1000, bool), blocks)
    means = vals.reshape(50, 20).mean(axis=1)
    loo = (means.sum() - means) / 49
    se_plain = np.sqrt(49 / 50 * np.sum((loo - loo.mean()) ** 2))
    assert est == pytest.approx(vals.mean())
    assert se == pytest.approx(se_plain, rel=1e-10)
    assert (n, g) == (1000, 50)


def test_f4_tree_and_admixture(freq):
    sym = fstats.f4(freq, "A", "B", "C", "O")
    assert abs(sym.z) < 3.5
    drift = fstats.f4(freq, "A", "C", "B", "O")
    assert drift.z > 5 and drift.estimate > 0
    assert sym.n_blocks > 50


def test_f3_admixture_signal(freq):
    admixed = fstats.f3(freq, "X", "A", "B")
    assert admixed.z < -3
    unadmixed = fstats.f3(freq, "C", "A", "O")
    assert unadmixed.estimate > 0 and unadmixed.z > 3


def test_f2_unbiased_within_population(sim):
    """Two disjoint halves of one population: true f2 = 0. The corrected estimator is ~0,
    the naive estimator is biased upward by the sampling variance."""
    lab = sim.labels.copy()
    a = np.flatnonzero(lab == "A")
    lab[a[:15]] = "A1"
    lab[a[15:]] = "A2"
    blocks = fstats.assign_blocks(sim.chrom, sim.pos, block_size=100_000)
    fd = fstats.FrequencyData.from_genotypes(sim.G, lab, block_ids=blocks)
    unb = fstats.f2(fd, "A1", "A2")
    naive = fstats.f2(fd, "A1", "A2", unbiased=False)
    assert abs(unb.z) < 3.5
    assert naive.estimate > 10 * naive.se


def test_f2_consistent_across_sample_sizes(sim):
    """Unbiased f2(A, C) from 3 individuals per population agrees with the estimate from all 30."""
    blocks = fstats.assign_blocks(sim.chrom, sim.pos, block_size=100_000)
    full = fstats.FrequencyData.from_genotypes(sim.G, sim.labels, block_ids=blocks)
    keep = np.zeros(len(sim.labels), bool)
    for p in ("A", "C"):
        keep[np.flatnonzero(sim.labels == p)[:3]] = True
    small = fstats.FrequencyData.from_genotypes(sim.G[keep], sim.labels[keep], block_ids=blocks)
    f_full = fstats.f2(full, "A", "C")
    f_small = fstats.f2(small, "A", "C")
    f_small_naive = fstats.f2(small, "A", "C", unbiased=False)
    assert abs(f_small.estimate - f_full.estimate) < 3 * f_small.se
    assert f_small_naive.estimate - f_full.estimate > 3 * f_small.se


def test_pseudohaploid_counts():
    G = np.array([[0, 2, 2], [2, 2, np.nan]], dtype=float)
    fd = fstats.FrequencyData.from_genotypes(
        G, ["p", "p"], block_ids=np.zeros(3), ploidy=np.array([1, 1])
    )
    np.testing.assert_allclose(fd.freqs[0], [0.5, 1.0, 1.0])
    np.testing.assert_allclose(fd.counts[0], [2, 2, 1])


def test_f2_blocks_consistent_with_f4(freq):
    f2b, cnt = fstats.f2_blocks(freq)
    i = {p: freq.index(p) for p in "ABCO"}
    w = cnt[i["A"], i["B"]]

    def m(x, y):
        return np.nansum(f2b[i[x], i[y]] * cnt[i[x], i[y]]) / cnt[i[x], i[y]].sum()

    f4_from_f2 = (m("A", "O") + m("B", "C") - m("A", "C") - m("B", "O")) / 2
    assert f4_from_f2 == pytest.approx(fstats.f4(freq, "A", "B", "C", "O").estimate, abs=2e-4)
    assert w.sum() > 0 and np.allclose(f2b, f2b.transpose(1, 0, 2), equal_nan=True)


def test_unknown_population(freq):
    with pytest.raises(KeyError):
        fstats.f4(freq, "A", "B", "C", "nope")
