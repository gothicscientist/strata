"""PCA tests on SYNTHETIC msprime data."""

from __future__ import annotations

import numpy as np
import pytest

from strata.analysis import pca


def _ref(sim):
    m = np.isin(sim.labels, ["A", "B", "C", "O"])
    return sim.G[m], sim.labels[m]


def test_normalisation_matches_smartpca_formula():
    G = np.array([[0, 1, 2], [2, 1, np.nan], [1, 1, 0]], dtype=float)
    mean, scale = pca.normalisation(G)
    np.testing.assert_allclose(mean, [1.0, 1.0, 1.0])
    p = (np.array([3.0, 3.0, 2.0]) + 1) / (2 * np.array([3, 3, 2]) + 2)
    np.testing.assert_allclose(scale, np.sqrt(p * (1 - p)))


def test_fit_separates_populations_and_variance_ordered(sim, ref_pca):
    _, labels = _ref(sim)
    model = ref_pca
    ev = model.explained_variance_ratio
    assert np.all(np.diff(ev) <= 1e-12) and ev.sum() < 1
    sc = model.reference_scores
    # PC1 separates the outgroup O from the rest.
    o = sc[labels == "O", 0]
    rest = sc[labels != "O", 0]
    assert min(abs(o.mean() - rest.mean()) / sc[:, 0].std(), 10) > 1.5


def test_projection_reproduces_reference_scores(sim, ref_pca):
    G, _ = _ref(sim)
    model = ref_pca
    coords, used = pca.project_array(G[:5], model)
    np.testing.assert_allclose(coords, model.reference_scores[:5], atol=1e-8)
    assert np.all(used == G.shape[1])


def test_heldout_projection_matches_full_pca(sim, ref_pca):
    G, labels = _ref(sim)
    rng = np.random.default_rng(0)
    held = np.zeros(len(labels), dtype=bool)
    for p in ["A", "B", "C", "O"]:
        held[rng.choice(np.flatnonzero(labels == p), 4, replace=False)] = True
    full = ref_pca
    part = pca.fit_reference_pca(G[~held], 3, seed=0)
    proj, _ = pca.project_array(G[held], part)
    target = full.reference_scores[held]
    for k in range(2):
        r = np.corrcoef(proj[:, k], target[:, k])[0, 1]
        assert abs(r) > 0.97, (k, r)
        # Least-squares projection is on the same scale as in-sample scores (within 25%).
        ratio = np.std(proj[:, k]) / np.std(target[:, k])
        assert 0.75 < ratio < 1.33


def test_projection_with_missing_snps(sim, ref_pca):
    model = ref_pca
    X = sim.G[sim.labels == "X"][:10].astype(float)
    full, _ = pca.project_array(X, model)
    rng = np.random.default_rng(3)
    Xm = X.copy()
    Xm[rng.random(X.shape) < 0.6] = np.nan
    part, used = pca.project_array(Xm, model)
    assert np.all(used < 0.5 * X.shape[1])
    err = np.abs(part - full)[:, :2]
    assert np.max(err) < 0.15 * np.ptp(model.reference_scores[:, :2], axis=0).min()


def test_too_few_snps_gives_nan():
    G = np.random.default_rng(0).integers(0, 3, (20, 50)).astype(float)
    model = pca.fit_reference_pca(G, 2)
    x = np.full(50, np.nan)
    x[:5] = 1
    coords, used = pca.project_array(x, model)
    assert used[0] == 5 and np.all(np.isnan(coords))


def test_randomized_and_exact_svd_agree():
    rng = np.random.default_rng(5)
    freqs = rng.uniform(0.05, 0.95, (3, 800))
    lab = np.repeat([0, 1, 2], 200)
    G = rng.binomial(2, freqs[lab]).astype(float)
    exact = pca.fit_reference_pca(G[:, :500], 3)  # min dim <= 500 -> exact
    approx = pca.fit_reference_pca(G[:, :500], 3)
    np.testing.assert_allclose(exact.singular_values, approx.singular_values)
    big = np.repeat(G, 2, axis=0)[:, :600]  # 1200 x 600 -> randomized path
    m1 = pca.fit_reference_pca(big, 2, seed=1)
    U, S, _ = np.linalg.svd(np.nan_to_num((big - m1.mean) / m1.scale), full_matrices=False)
    np.testing.assert_allclose(m1.singular_values, S[:2], rtol=1e-6)


def test_save_load_roundtrip(tmp_path, sim):
    G, labels = _ref(sim)
    model = pca.fit_reference_pca(G[:, :2000], 3, sample_ids=[f"i{i}" for i in range(len(G))])
    path = tmp_path / "m.npz"
    model.save(path)
    loaded = pca.PCAModel.load(path)
    np.testing.assert_array_equal(loaded.loadings, model.loadings)
    assert loaded.reference_ids == model.reference_ids
    x = G[:2, :2000]
    np.testing.assert_allclose(pca.project_array(x, loaded)[0], pca.project_array(x, model)[0])
    dumped = loaded.model_dump(mode="json")
    assert "loadings" not in dumped and dumped["n_components"] == 3


def test_population_centroids():
    coords = np.array([[0.0, 0], [2, 2], [10, 10], [np.nan, 1]])
    table, counts = pca.population_centroids(coords, ["a", "a", "b", "b"], space="s")
    assert table.names == ["a", "b"]
    np.testing.assert_allclose(table.matrix, [[1, 1], [10, 10]])
    assert counts == {"a": 2, "b": 1}


def test_project_wrong_length():
    model = pca.fit_reference_pca(np.random.default_rng(0).integers(0, 3, (10, 30)), 2)
    with pytest.raises(ValueError):
        pca.project_array(np.zeros(29), model)


def test_out_of_fold_scores_remove_shrinkage(sim, ref_pca):
    G, labels = _ref(sim)
    oof = pca.out_of_fold_scores(G, ref_pca, n_folds=5, groups=labels)
    xs, _ = pca.project_array(sim.G[sim.labels == "X"], ref_pca)
    # Out-of-fold reference coordinates and projected X are on the same scale, so the
    # simulated mixture X = 0.3 A + 0.7 B is recovered from them.
    from strata.analysis import admixture

    cent = {p: oof[labels == p, :4].mean(axis=0) for p in ["A", "B", "C"]}
    res = admixture.fit(
        xs[:, :4].mean(axis=0), np.vstack(list(cent.values())), source_names=list(cent)
    )
    w = res.weights()
    assert abs(w["A"] - 0.3) < 0.06 and abs(w["B"] - 0.7) < 0.06
    for k in range(2):
        assert abs(np.corrcoef(oof[:, k], ref_pca.reference_scores[:, k])[0, 1]) > 0.95
