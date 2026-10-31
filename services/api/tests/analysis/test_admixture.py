"""Exploratory admixture fitting tests (SYNTHETIC coordinates and msprime data)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from strata.analysis import admixture, pca
from strata.analysis.types import EXPLORATORY_CAVEAT, CoordinateTable

TRUE_ADMIX = {"A": 0.3, "B": 0.7}  # must match conftest demography


def _objective(A, t, w):
    r = A @ w - t
    return float(r @ r)


@pytest.mark.parametrize("seed", range(40))
def test_solvers_agree(seed):
    rng = np.random.default_rng(seed)
    k, d = int(rng.integers(1, 8)), int(rng.integers(2, 26))
    A = rng.normal(0, 0.1, (d, k))
    t = rng.normal(0, 0.1, d) if seed % 2 else A @ rng.dirichlet(np.ones(k))
    w_qp = admixture.solve_qp(A, t)
    w_nn = admixture.solve_nnls(A, t)
    w_sl, _ = admixture.solve_slsqp(A, t)
    for w in (w_qp, w_nn, w_sl):
        assert np.all(w >= 0) and np.isclose(w.sum(), 1.0)
    f = [_objective(A, t, w) for w in (w_qp, w_nn, w_sl)]
    assert f[0] <= min(f[1:]) + 1e-10
    assert abs(f[1] - f[0]) < 1e-8 and abs(f[2] - f[0]) < 1e-8


def test_solver_degenerate_duplicate_sources():
    A = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])  # first two sources identical
    t = np.array([0.5, 0.5])
    w = admixture.solve_qp(A, t)
    assert np.isclose(w[2], 0.5) and np.isclose(w[0] + w[1], 0.5)


def test_exact_mixture_recovered():
    rng = np.random.default_rng(1)
    S = rng.normal(0, 0.1, (4, 25))
    w = np.array([0.2, 0.5, 0.0, 0.3])
    res = admixture.fit(w @ S, S, source_names=list("abcd"), space="g25")
    np.testing.assert_allclose([s.weight for s in res.sources], w, atol=1e-9)
    assert res.distance < 1e-9
    assert res.kind == "exploratory" and res.caveat == EXPLORATORY_CAVEAT
    assert res.quality is not None and res.quality.label == "good"
    json.dumps(res.model_dump(mode="json"))


def test_methods_agree_in_fit():
    rng = np.random.default_rng(2)
    S = rng.normal(0, 0.1, (5, 25))
    t = rng.normal(0, 0.1, 25)
    fits = [admixture.fit(t, S, method=m) for m in ("qp", "nnls", "slsqp")]
    for f in fits[1:]:
        np.testing.assert_allclose(
            [s.weight for s in f.sources], [s.weight for s in fits[0].sources], atol=1e-4
        )
    assert fits[0].quality.label == "poor"  # random target far from the sources


def test_dim_weights_and_residuals():
    S = np.array([[0.0, 0.0], [1.0, 0.0]])
    t = np.array([0.25, 0.3])
    res = admixture.fit(t, S, dim_weights=np.array([1.0, 0.0]))
    np.testing.assert_allclose([s.weight for s in res.sources], [0.75, 0.25])
    np.testing.assert_allclose(res.residuals, [0.0, -0.3], atol=1e-12)
    assert res.distance == pytest.approx(0.0)


def test_fit_rejects_bad_input():
    with pytest.raises(ValueError):
        admixture.fit(np.zeros(3), np.zeros((2, 4)))
    with pytest.raises(ValueError):
        admixture.fit(np.array([np.nan, 0]), np.zeros((2, 2)))


@pytest.fixture(scope="module")
def projected(sim):
    """Fit PCA on half of each reference population and project everyone. Only projected
    (held-out) individuals are used as sources/targets below: in-sample reference scores are
    inflated relative to projected samples (smartpca shrinkage), and mixing the two biases
    mixture weights."""
    in_fit = np.zeros(len(sim.labels), dtype=bool)
    for p in ["A", "B", "C", "O"]:
        in_fit[np.flatnonzero(sim.labels == p)[:15]] = True
    model = pca.fit_reference_pca(sim.G[in_fit], 4, seed=0)
    coords, _ = pca.project_array(sim.G, model)
    coords[in_fit] = np.nan  # population_centroids ignores NaN rows
    return coords


def test_recovers_simulated_admixture_from_pca(sim, projected):
    table, _ = pca.population_centroids(projected, sim.labels, space="sim-pca")
    sources = table.subset(["A", "B", "C"])
    target = table.row("X")
    for method in ("qp", "nnls", "slsqp"):
        res = admixture.fit(target, sources, method=method, target_name="X")
        w = res.weights()
        assert abs(w["A"] - TRUE_ADMIX["A"]) < 0.06, w
        assert abs(w["B"] - TRUE_ADMIX["B"]) < 0.06, w
        assert w["C"] < 0.05


def test_bootstrap_ci_covers_truth(sim, projected):
    ok = np.all(np.isfinite(projected), axis=1)
    samples = {p: projected[(sim.labels == p) & ok] for p in ["A", "B", "C"]}
    res = admixture.bootstrap(
        projected[sim.labels == "X"].mean(axis=0),
        samples,
        n=200,
        seed=7,
        space="sim-pca",
        target_samples=projected[sim.labels == "X"],
    )
    ci = {w.name: w for w in res.weights}
    for p, truth in TRUE_ADMIX.items():
        assert ci[p].ci_low - 0.03 <= truth <= ci[p].ci_high + 0.03
        assert 0 < ci[p].se < 0.2
    assert res.kind == "exploratory" and res.n_bootstrap == 200
    again = admixture.bootstrap(
        projected[sim.labels == "X"].mean(axis=0),
        samples,
        n=200,
        seed=7,
        space="sim-pca",
        target_samples=projected[sim.labels == "X"],
    )
    assert again.model_dump() == res.model_dump()  # deterministic given seed


def test_rotation_prefers_true_sources(sim, projected):
    table, _ = pca.population_centroids(projected, sim.labels, space="sim-pca")
    cands = table.subset(["A", "B", "C", "O"])
    res = admixture.rotate(table.row("X"), cands, k_range=(1, 3))
    assert res.strategy == "exhaustive" and res.n_models_evaluated == 4 + 6 + 4
    pref = next(m for m in res.models if m.rank == res.preferred_rank)
    assert {s.name for s in pref.sources} == {"A", "B"}
    assert all(s.weight >= res.min_weight for m in res.models for s in m.sources)
    dists = [m.distance for m in res.models]
    assert dists == sorted(dists)


def test_rotation_prefiltered_when_capped():
    rng = np.random.default_rng(4)
    S = rng.normal(0, 0.1, (30, 10))
    t = 0.4 * S[3] + 0.6 * S[17]
    cands = CoordinateTable(space="s", names=[f"p{i}" for i in range(30)], matrix=S)
    res = admixture.rotate(t, cands, k_range=(1, 3), max_models=500, seed=1)
    assert res.strategy == "prefiltered" and res.n_models_evaluated <= 500
    assert {s.name for s in res.models[0].sources} == {"p3", "p17"}
    assert res.models[0].distance < 1e-8


def test_sensitivity(sim, projected):
    table, _ = pca.population_centroids(projected, sim.labels, space="sim-pca")
    res = admixture.sensitivity(table.row("X"), table.subset(["A", "B", "C"]), n_jitter=50)
    drop_a = next(x for x in res.leave_one_source_out if x.dropped == "A")
    drop_c = next(x for x in res.leave_one_source_out if x.dropped == "C")
    assert drop_a.delta_distance > 5 * max(drop_c.delta_distance, 1e-9)
    assert len(res.leave_one_dimension_out) == 4
    assert res.jitter is not None and res.jitter.n == 50
    assert res.kind == "exploratory"
    json.dumps(res.model_dump(mode="json"))
