"""Nearest populations / samples in a coordinate space."""

from __future__ import annotations

from typing import Literal

import numpy as np

from strata.analysis.types import CoordinateTable, NearestResult, Neighbor

Metric = Literal["euclidean", "weighted", "manhattan", "cosine"]


def distances(
    target: np.ndarray,
    matrix: np.ndarray,
    *,
    metric: Metric = "euclidean",
    weights: np.ndarray | None = None,
) -> np.ndarray:
    """Distances from ``target`` (d,) to each row of ``matrix`` (n, d).

    ``weighted`` uses sqrt(sum_d w_d (t_d - x_d)^2); pass PCA eigenvalues (or explained variance)
    as ``weights`` to weight axes by the variance they explain.
    """
    t = np.asarray(target, dtype=np.float64)
    X = np.asarray(matrix, dtype=np.float64)
    diff = X - t
    if metric == "euclidean":
        return np.sqrt(np.sum(diff * diff, axis=1))
    if metric == "weighted":
        if weights is None:
            raise ValueError("weighted metric requires weights")
        w = np.asarray(weights, dtype=np.float64)
        if w.shape != t.shape or np.any(w < 0):
            raise ValueError("weights must be non-negative with one value per dimension")
        return np.sqrt(np.sum(w * diff * diff, axis=1))
    if metric == "manhattan":
        return np.sum(np.abs(diff), axis=1)
    if metric == "cosine":
        denom = np.linalg.norm(X, axis=1) * np.linalg.norm(t)
        sim = np.divide(X @ t, denom, out=np.zeros(X.shape[0]), where=denom > 0)
        return 1.0 - sim
    raise ValueError(f"unknown metric {metric}")


def nearest(
    target: np.ndarray,
    table: CoordinateTable,
    k: int = 10,
    metric: Metric = "euclidean",
    *,
    weights: np.ndarray | None = None,
    target_name: str = "target",
    exclude: list[str] | None = None,
) -> NearestResult:
    d = distances(target, table.matrix, metric=metric, weights=weights)
    order = np.argsort(d, kind="stable")
    excl = set(exclude or [])
    neighbors: list[Neighbor] = []
    for i in order:
        if table.names[i] in excl or not np.isfinite(d[i]):
            continue
        neighbors.append(
            Neighbor(rank=len(neighbors) + 1, name=table.names[i], distance=float(d[i]))
        )
        if len(neighbors) >= k:
            break
    return NearestResult(space=table.space, target=target_name, metric=metric, neighbors=neighbors)
