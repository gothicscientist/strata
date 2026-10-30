"""smartpca-style PCA on reference genotypes and least-squares projection of new samples.

Normalisation (Patterson, Price & Reich 2006): for SNP j with observed mean dosage mu_j and
smoothed allele frequency p_j = (sum_i g_ij + 1) / (2 n_j + 2), x_ij = (g_ij - mu_j) /
sqrt(p_j (1 - p_j)). Missing genotypes are mean-imputed (x = 0) for fitting. Projection of new
samples solves min_t || V_obs t - x_obs ||^2 over observed SNPs only (smartpca
``lsqproject: YES``), which for a fully observed reference sample reproduces its fitted score.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pydantic import Field
from sklearn.utils.extmath import randomized_svd

from strata.analysis.types import CoordinateTable, PCAProjection
from strata.io.types import ArrayModel, NDArray


class PCAModel(ArrayModel):
    space: str = "strata-pca-v1"
    n_components: int
    mean: NDArray = Field(exclude=True, description="per-SNP mean dosage (2p)")
    scale: NDArray = Field(exclude=True, description="per-SNP sqrt(p(1-p))")
    loadings: NDArray = Field(exclude=True, description="(n_snps, k) right singular vectors")
    singular_values: NDArray
    eigenvalues: NDArray
    explained_variance_ratio: NDArray
    reference_scores: NDArray = Field(exclude=True)
    reference_ids: list[str] = Field(default_factory=list, exclude=True)
    snp_ids: NDArray | None = Field(None, exclude=True)
    n_reference: int
    n_snps: int

    def save(self, path: str | Path) -> None:
        np.savez_compressed(
            path,
            space=np.array(self.space),
            mean=self.mean,
            scale=self.scale,
            loadings=self.loadings,
            singular_values=self.singular_values,
            eigenvalues=self.eigenvalues,
            explained_variance_ratio=self.explained_variance_ratio,
            reference_scores=self.reference_scores,
            reference_ids=np.array(self.reference_ids, dtype=str),
            snp_ids=np.array([] if self.snp_ids is None else self.snp_ids, dtype=str),
        )

    @classmethod
    def load(cls, path: str | Path) -> PCAModel:
        with np.load(path, allow_pickle=False) as z:
            snp_ids = z["snp_ids"]
            return cls(
                space=str(z["space"]),
                n_components=int(z["loadings"].shape[1]),
                mean=z["mean"],
                scale=z["scale"],
                loadings=z["loadings"],
                singular_values=z["singular_values"],
                eigenvalues=z["eigenvalues"],
                explained_variance_ratio=z["explained_variance_ratio"],
                reference_scores=z["reference_scores"],
                reference_ids=[str(s) for s in z["reference_ids"]],
                snp_ids=snp_ids.astype(object) if snp_ids.size else None,
                n_reference=int(z["reference_scores"].shape[0]),
                n_snps=int(z["mean"].shape[0]),
            )


def _as_float(G: np.ndarray) -> np.ndarray:
    G = np.asarray(G)
    if G.dtype.kind in "iu":
        out = G.astype(np.float64)
        out[(G < 0) | (G > 2)] = np.nan
        return out
    return G.astype(np.float64, copy=False)


def normalisation(G: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-SNP mean (2p) and sqrt(p(1-p)) with smartpca's +1/+2 frequency smoothing."""
    obs = np.isfinite(G)
    n = obs.sum(axis=0)
    s = np.where(obs, G, 0.0).sum(axis=0)
    mean = np.divide(s, n, out=np.zeros(G.shape[1]), where=n > 0)
    p = (s + 1.0) / (2.0 * n + 2.0)
    return mean, np.sqrt(p * (1.0 - p))


def fit_reference_pca(
    G: np.ndarray,
    n_components: int = 10,
    *,
    seed: int = 0,
    sample_ids: list[str] | None = None,
    snp_ids: np.ndarray | None = None,
    space: str = "strata-pca-v1",
    n_iter: int = 7,
) -> PCAModel:
    """Fit PCA on reference dosages ``G`` (n_individuals, n_snps); NaN or -1 = missing."""
    X = _as_float(G)
    n, m = X.shape
    if n < 2 or m < 2:
        raise ValueError("need at least 2 individuals and 2 SNPs")
    k = int(min(n_components, n - 1, m))
    mean, scale = normalisation(X)
    Xs = (X - mean) / scale
    Xs[~np.isfinite(Xs)] = 0.0
    total_ss = float(np.sum(Xs * Xs))
    if min(n, m) <= 500:
        U, S, Vt = np.linalg.svd(Xs, full_matrices=False)
        U, S, Vt = U[:, :k], S[:k], Vt[:k]
    else:
        U, S, Vt = randomized_svd(Xs, k, n_iter=n_iter, random_state=seed)
    # Deterministic sign convention: largest-|loading| entry of each axis positive.
    signs = np.sign(Vt[np.arange(k), np.argmax(np.abs(Vt), axis=1)])
    signs[signs == 0] = 1.0
    U, Vt = U * signs, Vt * signs[:, None]
    return PCAModel(
        space=space,
        n_components=k,
        mean=mean,
        scale=scale,
        loadings=Vt.T.copy(),
        singular_values=S,
        eigenvalues=S**2 / (n - 1),
        explained_variance_ratio=S**2 / total_ss if total_ss > 0 else np.zeros(k),
        reference_scores=U * S,
        reference_ids=list(sample_ids) if sample_ids is not None else [],
        snp_ids=None if snp_ids is None else np.asarray(snp_ids, dtype=object),
        n_reference=n,
        n_snps=m,
    )


def project_array(
    dosages: np.ndarray, model: PCAModel, *, min_snps: int | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Project samples (n, n_snps) or (n_snps,). Returns (coords (n, k), n_snps_used (n,)).

    Samples with fewer than ``min_snps`` observed SNPs (default 10 * k) get NaN coordinates.
    """
    D = _as_float(np.atleast_2d(dosages))
    if D.shape[1] != model.n_snps:
        raise ValueError(f"expected {model.n_snps} SNPs, got {D.shape[1]}")
    k = model.n_components
    min_snps = 10 * k if min_snps is None else min_snps
    V = model.loadings
    out = np.full((D.shape[0], k), np.nan)
    used = np.zeros(D.shape[0], dtype=np.int64)
    for i, g in enumerate(D):
        obs = np.isfinite(g)
        used[i] = int(obs.sum())
        if used[i] < max(min_snps, k):
            continue
        x = (g[obs] - model.mean[obs]) / model.scale[obs]
        Vo = V[obs]
        out[i] = np.linalg.lstsq(Vo, x, rcond=None)[0]
    return out, used


def project(
    sample_dosages: np.ndarray,
    model: PCAModel,
    *,
    names: list[str] | None = None,
    min_snps: int | None = None,
) -> PCAProjection:
    coords, used = project_array(sample_dosages, model, min_snps=min_snps)
    names = names or [f"sample{i + 1}" for i in range(coords.shape[0])]
    return PCAProjection(
        space=model.space,
        names=names,
        coordinates=[[float(v) for v in row] for row in coords],
        n_snps_used=[int(u) for u in used],
        explained_variance_ratio=[float(v) for v in model.explained_variance_ratio],
    )


def population_centroids(
    coords: np.ndarray, labels: list[str] | np.ndarray, *, space: str
) -> tuple[CoordinateTable, dict[str, int]]:
    """Mean coordinates per population label (NaN rows ignored) and sample counts."""
    coords = np.asarray(coords, dtype=np.float64)
    labels = np.asarray(labels, dtype=object)
    names: list[str] = []
    rows: list[np.ndarray] = []
    counts: dict[str, int] = {}
    for lab in dict.fromkeys(labels.tolist()):
        sub = coords[labels == lab]
        sub = sub[np.all(np.isfinite(sub), axis=1)]
        if sub.shape[0] == 0:
            continue
        names.append(str(lab))
        rows.append(sub.mean(axis=0))
        counts[str(lab)] = int(sub.shape[0])
    matrix = np.vstack(rows) if rows else np.zeros((0, coords.shape[1]))
    return CoordinateTable(space=space, names=names, matrix=matrix), counts
