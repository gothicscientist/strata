"""Exploratory constrained mixture fitting in coordinate spaces (G25 / Strata PCA).

Solves  min_w || sum_i w_i s_i - t ||^2  subject to  w_i >= 0, sum_i w_i = 1.

Three solvers are provided and cross-checked in tests:
* ``qp``    exact primal active-set method on the simplex (default; deterministic, fast),
* ``nnls``  Lawson-Hanson NNLS with a heavily weighted sum-to-one row (penalty method),
* ``slsqp`` scipy SLSQP with bounds and an equality constraint.

Every result is ``kind="exploratory"`` and carries ``EXPLORATORY_CAVEAT``; these fits are not
formal tests of admixture (see ``strata.qpadm`` for f-statistics based qpAdm).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from typing import Literal

import numpy as np
from scipy.optimize import minimize, nnls

from strata.analysis.types import (
    AdmixtureFit,
    BootstrapResult,
    CoordinateTable,
    FitQuality,
    JitterSummary,
    LeaveOneOut,
    RotationModel,
    RotationResult,
    SensitivityResult,
    SourceWeight,
    WeightCI,
)

Method = Literal["qp", "nnls", "slsqp"]
_EPS = 1e-12


# --------------------------------------------------------------------------- solvers


def _eqp(A: np.ndarray, t: np.ndarray, P: list[int]) -> np.ndarray:
    """Equality-constrained LS on columns P: min ||A_P z - t|| s.t. sum z = 1 (KKT system)."""
    Ap = A[:, P]
    p = len(P)
    K = np.zeros((p + 1, p + 1))
    K[:p, :p] = Ap.T @ Ap
    K[:p, p] = 1.0
    K[p, :p] = 1.0
    rhs = np.concatenate([Ap.T @ t, [1.0]])
    sol = np.linalg.lstsq(K, rhs, rcond=None)[0]
    return sol[:p]


def solve_qp(
    A: np.ndarray, t: np.ndarray, *, tol: float = 1e-10, max_iter: int | None = None
) -> np.ndarray:
    """Exact simplex-constrained least squares via a primal active-set method.

    ``A`` is (d, k) with sources as columns. Starts from the best single source (feasible) and
    adds/removes sources using KKT multipliers until optimality.
    """
    d, k = A.shape
    if k == 1:
        return np.ones(1)
    single = np.sum((A - t[:, None]) ** 2, axis=0)
    w = np.zeros(k)
    j0 = int(np.argmin(single))
    w[j0] = 1.0
    P = [j0]
    scale = max(float(np.max(np.abs(A))), 1.0) ** 2
    max_iter = max_iter or 10 * k + 20
    for _ in range(max_iter):
        z = _eqp(A, t, P)
        if np.all(z > -tol):
            w = np.zeros(k)
            w[P] = np.maximum(z, 0.0)
            w /= w.sum()
            g = A.T @ (A @ w - t)
            nu = -float(np.mean(g[P]))
            lam = g + nu
            inactive = [i for i in range(k) if i not in P]
            if not inactive:
                break
            i_min = min(inactive, key=lambda i: lam[i])
            if lam[i_min] >= -tol * scale:
                break
            P.append(i_min)
            continue
        # Step towards z until a passive weight hits zero.
        wP = w[P]
        neg = z < -tol
        alpha = np.min(wP[neg] / (wP[neg] - z[neg]))
        wP = wP + alpha * (z - wP)
        w[P] = wP
        P = [i for i, v in zip(P, wP, strict=True) if v > tol]
        if not P:
            P = [j0]
            w[:] = 0.0
            w[j0] = 1.0
        w = np.maximum(w, 0.0)
        w /= w.sum()
    return w


def solve_nnls(A: np.ndarray, t: np.ndarray, *, penalty: float | None = None) -> np.ndarray:
    k = A.shape[1]
    lam = penalty if penalty is not None else 1e4 * max(1.0, float(np.linalg.norm(A, ord=2)))
    Aa = np.vstack([A, lam * np.ones((1, k))])
    ta = np.concatenate([t, [lam]])
    w, _ = nnls(Aa, ta, maxiter=50 * k)
    s = w.sum()
    return w / s if s > 0 else np.full(k, 1.0 / k)


def solve_slsqp(A: np.ndarray, t: np.ndarray) -> tuple[np.ndarray, bool]:
    k = A.shape[1]
    AtA = A.T @ A
    Att = A.T @ t

    def f(w: np.ndarray) -> float:
        r = A @ w - t
        return float(r @ r)

    def grad(w: np.ndarray) -> np.ndarray:
        return 2.0 * (AtA @ w - Att)

    res = minimize(
        f,
        np.full(k, 1.0 / k),
        jac=grad,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * k,
        constraints=[{"type": "eq", "fun": lambda w: np.sum(w) - 1.0, "jac": lambda w: np.ones(k)}],
        options={"ftol": 1e-15, "maxiter": 1000},
    )
    w = np.clip(res.x, 0.0, None)
    return w / w.sum(), bool(res.success)


def solve(A: np.ndarray, t: np.ndarray, method: Method = "qp") -> tuple[np.ndarray, bool]:
    if method == "qp":
        return solve_qp(A, t), True
    if method == "nnls":
        return solve_nnls(A, t), True
    if method == "slsqp":
        return solve_slsqp(A, t)
    raise ValueError(f"unknown method {method}")


# --------------------------------------------------------------------------- helpers


def _sources_matrix(
    sources: CoordinateTable | np.ndarray, source_names: Sequence[str] | None
) -> tuple[np.ndarray, list[str], str | None]:
    if isinstance(sources, CoordinateTable):
        return np.asarray(sources.matrix, dtype=np.float64), list(sources.names), sources.space
    S = np.atleast_2d(np.asarray(sources, dtype=np.float64))
    names = list(source_names) if source_names is not None else [f"S{i + 1}" for i in range(len(S))]
    if len(names) != S.shape[0]:
        raise ValueError("source_names length must match number of sources")
    return S, names, None


def _median_pairwise(S: np.ndarray) -> float | None:
    if S.shape[0] < 2:
        return None
    d = [float(np.linalg.norm(a - b)) for a, b in itertools.combinations(S, 2)]
    m = float(np.median(d))
    return m if m > 0 else None


def _quality(
    t: np.ndarray, S: np.ndarray, names: list[str], dist: float, scale: float | None
) -> FitQuality | None:
    single = np.linalg.norm(S - t, axis=1)
    j = int(np.argmin(single))
    if scale is None:
        return None
    rel = dist / scale
    label: Literal["good", "fair", "poor"] = (
        "good" if rel < 0.1 else "fair" if rel < 0.25 else "poor"
    )
    imp = 1.0 - dist / single[j] if single[j] > 0 else 0.0
    return FitQuality(
        label=label,
        distance=dist,
        relative_distance=rel,
        best_single_source=names[j],
        best_single_distance=float(single[j]),
        improvement_over_single=max(0.0, float(imp)),
    )


# --------------------------------------------------------------------------- public API


def fit(
    target: np.ndarray,
    sources: CoordinateTable | np.ndarray,
    *,
    source_names: Sequence[str] | None = None,
    method: Method = "qp",
    space: str | None = None,
    target_name: str = "target",
    dim_weights: np.ndarray | None = None,
    quality_scale: float | None = None,
) -> AdmixtureFit:
    """Fit ``target`` (d,) as a convex mixture of ``sources`` (k, d).

    ``dim_weights`` (d,) weights squared residuals per dimension (e.g. PCA eigenvalues).
    ``quality_scale`` sets the distance scale for the fit-quality label (default: median
    pairwise distance among the given sources).
    """
    S, names, tspace = _sources_matrix(sources, source_names)
    t = np.asarray(target, dtype=np.float64)
    if S.shape[1] != t.shape[0]:
        raise ValueError("target and sources must have the same dimensionality")
    if not (np.all(np.isfinite(S)) and np.all(np.isfinite(t))):
        raise ValueError("coordinates must be finite")
    sw = np.ones_like(t) if dim_weights is None else np.sqrt(np.asarray(dim_weights, float))
    w, ok = solve((S * sw).T, t * sw, method)
    fitted = w @ S
    resid = fitted - t
    dist = float(np.linalg.norm(resid * sw))
    scale = quality_scale if quality_scale is not None else _median_pairwise(S * sw)
    return AdmixtureFit(
        space=space or tspace or "unspecified",
        target=target_name,
        method=method,
        sources=[SourceWeight(name=n, weight=float(x)) for n, x in zip(names, w, strict=True)],
        distance=dist,
        residuals=[float(v) for v in resid],
        fitted=[float(v) for v in fitted],
        quality=_quality(t * sw, S * sw, names, dist, scale),
        converged=ok,
    )


def bootstrap(
    target: np.ndarray,
    sources_samples: Mapping[str, np.ndarray],
    n: int = 500,
    seed: int = 0,
    *,
    method: Method = "qp",
    space: str = "unspecified",
    target_name: str = "target",
    target_samples: np.ndarray | None = None,
) -> BootstrapResult:
    """Resample individuals (with replacement) within each source population and, optionally,
    within the target group; refit on resampled centroids. Returns 2.5/97.5% percentile CIs."""
    names = list(sources_samples)
    samples = [np.atleast_2d(np.asarray(sources_samples[k], dtype=np.float64)) for k in names]
    if any(s.shape[0] == 0 for s in samples):
        raise ValueError("every source needs at least one individual")
    rng = np.random.default_rng(seed)
    t0 = np.asarray(target, dtype=np.float64)
    if target_samples is not None:
        target_samples = np.atleast_2d(np.asarray(target_samples, dtype=np.float64))
        t0 = target_samples.mean(axis=0)
    S0 = np.vstack([s.mean(axis=0) for s in samples])
    point = fit(t0, S0, source_names=names, method=method, space=space, target_name=target_name)
    W = np.empty((n, len(names)))
    D = np.empty(n)
    for b in range(n):
        Sb = np.vstack([s[rng.integers(0, s.shape[0], s.shape[0])].mean(axis=0) for s in samples])
        tb = t0
        if target_samples is not None:
            tb = target_samples[rng.integers(0, target_samples.shape[0], target_samples.shape[0])]
            tb = tb.mean(axis=0)
        w, _ = solve(Sb.T, tb, method)
        W[b] = w
        D[b] = float(np.linalg.norm(w @ Sb - tb))
    lo, hi = np.percentile(W, [2.5, 97.5], axis=0)
    single_pop = [k for k, s in zip(names, samples, strict=True) if s.shape[0] < 2]
    resampled = "individuals within each source population"
    if target_samples is not None:
        resampled += " and within the target group"
    if single_pop:
        resampled += f" (no resampling possible for single-individual sources: {single_pop})"
    pw = point.weights()
    return BootstrapResult(
        space=space,
        target=target_name,
        n_bootstrap=n,
        seed=seed,
        resampled=resampled,
        point=point,
        weights=[
            WeightCI(
                name=k,
                weight=pw[k],
                mean=float(W[:, i].mean()),
                se=float(W[:, i].std(ddof=1)) if n > 1 else 0.0,
                ci_low=float(lo[i]),
                ci_high=float(hi[i]),
            )
            for i, k in enumerate(names)
        ],
        distance_mean=float(D.mean()),
        distance_ci=(float(np.percentile(D, 2.5)), float(np.percentile(D, 97.5))),
    )


def _n_models(n: int, k_min: int, k_max: int) -> int:
    return sum(math.comb(n, k) for k in range(k_min, min(k_max, n) + 1))


def rotate(
    target: np.ndarray,
    candidates: CoordinateTable,
    k_range: tuple[int, int] = (1, 3),
    max_models: int = 20000,
    seed: int = 0,
    *,
    min_weight: float = 0.01,
    top_n: int = 25,
    tolerance: float = 0.05,
    method: Method = "qp",
    target_name: str = "target",
) -> RotationResult:
    """Rank source combinations of size k_range[0]..k_range[1] by fit distance.

    Exhaustive if the number of combinations is <= ``max_models``. Otherwise half the budget
    is spent exhaustively on a prefiltered candidate set (sources used by the all-candidate fit,
    then nearest candidates) and the other half on uniformly random combinations of all
    candidates (seeded). Each fit is pruned for parsimony: sources with weight < ``min_weight``
    are dropped and the model refitted. ``preferred_rank`` is the model with the fewest sources
    whose distance is within (1 + tolerance) x the best distance.
    """
    k_min, k_max = k_range
    if k_min < 1 or k_max < k_min:
        raise ValueError("invalid k_range")
    S, names = np.asarray(candidates.matrix, float), list(candidates.names)
    t = np.asarray(target, dtype=np.float64)
    n = len(names)
    total = _n_models(n, k_min, k_max)
    combos: list[tuple[int, ...]]
    prefiltered: list[str] | None = None
    if total <= max_models:
        strategy = "exhaustive"
        combos = [
            c for k in range(k_min, min(k_max, n) + 1) for c in itertools.combinations(range(n), k)
        ]
    else:
        strategy = "prefiltered"
        budget = max_models // 2
        full_w, _ = solve(S.T, t, method)
        by_weight = [int(i) for i in np.argsort(-full_w) if full_w[i] > 1e-6]
        by_dist = [int(i) for i in np.argsort(np.linalg.norm(S - t, axis=1))]
        order = list(dict.fromkeys(by_weight + by_dist))
        m = k_max
        while m < n and _n_models(m + 1, k_min, k_max) <= budget:
            m += 1
        pre = order[:m]
        prefiltered = [names[i] for i in pre]
        seen = set()
        combos = []
        for k in range(k_min, min(k_max, m) + 1):
            for c in itertools.combinations(sorted(pre), k):
                seen.add(c)
                combos.append(c)
        rng = np.random.default_rng(seed)
        ks = np.arange(k_min, min(k_max, n) + 1)
        kw = np.array([math.comb(n, int(k)) for k in ks], dtype=float)
        tries = 0
        while len(combos) < max_models and tries < 20 * max_models:
            tries += 1
            k = int(rng.choice(ks, p=kw / kw.sum()))
            c = tuple(sorted(int(x) for x in rng.choice(n, size=k, replace=False)))
            if c not in seen:
                seen.add(c)
                combos.append(c)

    scale = _median_pairwise(S)
    best: dict[frozenset[int], tuple[float, np.ndarray, tuple[int, ...] | None]] = {}
    for c in combos:
        idx = list(c)
        w, _ = solve(S[idx].T, t, method)
        pruned_from = None
        keep = [i for i, x in zip(idx, w, strict=True) if x >= min_weight]
        if len(keep) < len(idx) and keep:
            pruned_from = c
            idx = keep
            w, _ = solve(S[idx].T, t, method)
        dist = float(np.linalg.norm(w @ S[idx] - t))
        key = frozenset(idx)
        if key not in best or dist < best[key][0] - 1e-15:
            ordered = sorted(zip(idx, w, strict=True))
            best[key] = (dist, np.array([x for _, x in ordered]), pruned_from)
    ranked = sorted(best.items(), key=lambda kv: (kv[1][0], len(kv[0])))
    models = []
    for r, (key, (dist, w, pf)) in enumerate(ranked[:top_n], start=1):
        idx = sorted(key)
        models.append(
            RotationModel(
                rank=r,
                sources=[
                    SourceWeight(name=names[i], weight=float(x))
                    for i, x in zip(idx, w, strict=True)
                ],
                distance=dist,
                n_sources=len(idx),
                pruned_from=[names[i] for i in pf] if pf else None,
            )
        )
    preferred = None
    if models:
        cutoff = models[0].distance * (1.0 + tolerance) + 1e-12
        if scale is not None:
            cutoff = max(cutoff, models[0].distance + 1e-6 * scale)
        within = [m for m in models if m.distance <= cutoff]
        preferred = min(within, key=lambda m: (m.n_sources, m.distance)).rank
    return RotationResult(
        space=candidates.space,
        target=target_name,
        k_range=(k_min, k_max),
        n_candidates=n,
        n_models_evaluated=len(combos),
        strategy=strategy,  # type: ignore[arg-type]
        prefiltered_candidates=prefiltered,
        min_weight=min_weight,
        models=models,
        preferred_rank=preferred,
        tolerance=tolerance,
    )


def sensitivity(
    target: np.ndarray,
    sources: CoordinateTable,
    *,
    method: Method = "qp",
    jitter_sd: float | None = None,
    n_jitter: int = 200,
    seed: int = 0,
    target_name: str = "target",
) -> SensitivityResult:
    """Leave-one-source-out, leave-one-dimension-out and target-jitter stability checks.

    The default jitter SD is the base residual spread per dimension (distance / sqrt(d)), i.e.
    perturbations comparable in size to what the model already fails to explain.
    """
    S, names = np.asarray(sources.matrix, float), list(sources.names)
    t = np.asarray(target, dtype=np.float64)
    base = fit(t, sources, method=method, target_name=target_name)
    bw = np.array([s.weight for s in base.sources])
    d = t.shape[0]

    loso: list[LeaveOneOut] = []
    if len(names) >= 2:
        for j, nm in enumerate(names):
            keep = [i for i in range(len(names)) if i != j]
            w, _ = solve(S[keep].T, t, method)
            dist = float(np.linalg.norm(w @ S[keep] - t))
            full = np.zeros(len(names))
            full[keep] = w
            loso.append(
                LeaveOneOut(
                    dropped=nm,
                    distance=dist,
                    delta_distance=dist - base.distance,
                    weights=[
                        SourceWeight(name=names[i], weight=float(x))
                        for i, x in zip(keep, w, strict=True)
                    ],
                    max_abs_weight_change=float(np.max(np.abs(full - bw)[keep])),
                )
            )
    lodo: list[LeaveOneOut] = []
    if d >= 2:
        dim_names = sources.dim_names or [f"PC{i + 1}" for i in range(d)]
        for j in range(d):
            keep = [i for i in range(d) if i != j]
            w, _ = solve(S[:, keep].T, t[keep], method)
            dist = float(np.linalg.norm(w @ S[:, keep] - t[keep]))
            base_red = float(np.linalg.norm(bw @ S[:, keep] - t[keep]))
            lodo.append(
                LeaveOneOut(
                    dropped=dim_names[j],
                    distance=dist,
                    delta_distance=dist - base_red,
                    weights=[
                        SourceWeight(name=n, weight=float(x)) for n, x in zip(names, w, strict=True)
                    ],
                    max_abs_weight_change=float(np.max(np.abs(w - bw))),
                )
            )
    jitter = None
    if n_jitter > 0:
        sd = jitter_sd if jitter_sd is not None else max(base.distance / math.sqrt(d), 1e-6)
        rng = np.random.default_rng(seed)
        W = np.array([solve(S.T, t + rng.normal(0.0, sd, d), method)[0] for _ in range(n_jitter)])
        wsd = W.std(axis=0, ddof=1) if n_jitter > 1 else np.zeros(len(names))
        jitter = JitterSummary(
            sd=sd,
            n=n_jitter,
            weight_sd=[
                SourceWeight(name=n, weight=float(x)) for n, x in zip(names, wsd, strict=True)
            ],
            max_weight_sd=float(wsd.max()),
        )
    max_lodo = max((x.max_abs_weight_change for x in lodo), default=0.0)
    max_jit = jitter.max_weight_sd if jitter else 0.0
    stable = max_lodo < 0.10 and max_jit < 0.05
    note = (
        f"Largest weight change when dropping one dimension: {max_lodo:.3f}; largest weight SD "
        f"under target jitter: {max_jit:.3f}. "
        + (
            "Weights look stable to these perturbations."
            if stable
            else "Weights are sensitive to small perturbations; interpret proportions with caution."
        )
    )
    return SensitivityResult(
        space=sources.space,
        target=target_name,
        base=base,
        leave_one_source_out=loso,
        leave_one_dimension_out=lodo,
        jitter=jitter,
        stable=stable,
        stability_note=note,
    )
