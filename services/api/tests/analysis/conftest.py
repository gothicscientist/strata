"""SYNTHETIC msprime fixtures (labelled synthetic; never presented as real data).

Demography (generations ago): O splits from the rest at 4000; C from AB at 2000; A and B
split at 1000; X is formed 20 generations ago as 0.3 A + 0.7 B. Each "chromosome" is an
independent 0.4 Mb simulation so block-jackknife blocks are realistic and independent.
"""

from __future__ import annotations

from dataclasses import dataclass

import msprime
import numpy as np
import pytest

TRUE_ADMIX = {"A": 0.3, "B": 0.7}
POPS = ["A", "B", "C", "O", "X"]


@dataclass
class SimData:
    G: np.ndarray  # (n_ind, n_snp) diploid dosages of the derived allele
    labels: np.ndarray
    chrom: np.ndarray
    pos: np.ndarray


def _demography() -> msprime.Demography:
    d = msprime.Demography()
    for name in ["A", "B", "C", "O", "X", "AB", "ABC", "ANC"]:
        d.add_population(name=name, initial_size=10_000)
    d.add_admixture(time=20, derived="X", ancestral=["A", "B"], proportions=[0.3, 0.7])
    d.add_population_split(time=1000, derived=["A", "B"], ancestral="AB")
    d.add_population_split(time=2000, derived=["AB", "C"], ancestral="ABC")
    d.add_population_split(time=4000, derived=["ABC", "O"], ancestral="ANC")
    d.sort_events()
    return d


@pytest.fixture(scope="session")
def sim() -> SimData:
    n_per = 30
    demo = _demography()
    blocks = []
    chroms = []
    positions = []
    for c in range(1, 21):
        ts = msprime.sim_ancestry(
            samples={p: n_per for p in POPS},
            demography=demo,
            sequence_length=400_000,
            recombination_rate=1e-8,
            random_seed=1000 + c,
        )
        ts = msprime.sim_mutations(ts, rate=1.25e-8, random_seed=2000 + c, model="binary")
        H = ts.genotype_matrix()  # (sites, haplotypes)
        keep = (H.max(axis=1) == 1) & (H.sum(axis=1) > 0) & (H.sum(axis=1) < H.shape[1])
        H = H[keep]
        pos = np.array([s.position for s in ts.sites()])[keep].astype(np.int64) + 1
        _, uniq = np.unique(pos, return_index=True)
        H, pos = H[uniq], pos[uniq]
        blocks.append((H[:, 0::2] + H[:, 1::2]).T)  # diploid dosage (n_ind, sites)
        chroms.append(np.full(pos.size, str(c), dtype=object))
        positions.append(pos)
    G = np.concatenate(blocks, axis=1).astype(np.int8)
    labels = np.repeat(POPS, n_per).astype(object)
    return SimData(G=G, labels=labels, chrom=np.concatenate(chroms), pos=np.concatenate(positions))


@pytest.fixture(scope="session")
def ref_pca(sim):
    from strata.analysis import pca

    m = np.isin(sim.labels, ["A", "B", "C", "O"])
    return pca.fit_reference_pca(sim.G[m], 4, seed=0)
