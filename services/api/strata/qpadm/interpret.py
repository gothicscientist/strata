"""Turn a qpAdm fit into a guarded, human-readable verdict.

This encodes the reporting conventions that are standard in the qpAdm
literature — a model is usually called "fitting" when it is not rejected at
p > 0.05 and all admixture weights lie in [0, 1] — and nothing more. It is a
presentation aid, deliberately not a model-selection procedure: the thresholds
are conventions, not decision theory, and every verdict ships with the reasons
that produced it so a reader can disagree with the thresholds.
"""

from __future__ import annotations

from .types import Feasibility, QpAdmResult, RotateModelResult, WeightRow

# Conventional qpAdm reporting thresholds.
P_PLAUSIBLE = 0.05
P_MARGINAL = 0.01
# A weight may sit a hair outside [0, 1] from numerical noise in the
# unconstrained solve; only call it infeasible beyond this.
WEIGHT_TOLERANCE = 1e-6
# SE larger than half the weight means the weight carries little information.
MAX_RELATIVE_SE = 0.5
# Below this reciprocal condition number the f4 variance matrix is effectively
# singular and the reported standard errors are numerically tight rather than
# statistically meaningful. Matches ADMIXTOOLS 2's own concern bar.
RCOND_CONCERN = 1e-8


def _weights_in_unit_interval(weights: list[WeightRow]) -> bool | None:
    values = [w.weight for w in weights if w.weight is not None]
    if not values:
        return None
    lo, hi = -WEIGHT_TOLERANCE, 1.0 + WEIGHT_TOLERANCE
    return all(lo <= v <= hi for v in values)


def _weights_well_determined(weights: list[WeightRow]) -> bool | None:
    pairs = [(w.weight, w.se) for w in weights if w.weight is not None and w.se is not None]
    pairs = [(w, s) for w, s in pairs if s == s and s >= 0]  # drop NaN SEs
    if not pairs:
        return None
    for weight, se in pairs:
        denom = max(abs(weight), WEIGHT_TOLERANCE)
        if se / denom > MAX_RELATIVE_SE:
            return False
    return True


def assess_fit(
    *,
    p: float | None,
    weights: list[WeightRow],
    f4_var_rcond: float | None = None,
    p_threshold: float = P_PLAUSIBLE,
    marginal_p_threshold: float = P_MARGINAL,
) -> Feasibility:
    """Assess one qpAdm model fit.

    Args:
        p: Overall fit p-value for the full-rank model.
        weights: Estimated admixture weights with standard errors.
        f4_var_rcond: Reciprocal condition number of the inverted f4 variance
            matrix, if ADMIXTOOLS reported one.
        p_threshold: Above this the model is not rejected.
        marginal_p_threshold: Below this the model is rejected outright;
            between the two it is reported as marginal.

    Returns:
        A :class:`Feasibility` with a verdict and the reasons behind it.
    """
    if marginal_p_threshold > p_threshold:
        raise ValueError("'marginal_p_threshold' must be <= 'p_threshold'")

    reasons: list[str] = []
    in_unit = _weights_in_unit_interval(weights)
    well_determined = _weights_well_determined(weights)
    well_conditioned: bool | None = None
    if f4_var_rcond is not None and f4_var_rcond == f4_var_rcond:
        well_conditioned = f4_var_rcond >= RCOND_CONCERN

    p_passes: bool | None = None
    if p is None or p != p:
        reasons.append("No overall fit p-value was returned, so the model cannot be assessed.")
        verdict = "undetermined"
    else:
        p_passes = p > p_threshold
        if p <= marginal_p_threshold:
            verdict = "rejected"
            reasons.append(
                f"The model is rejected: p = {p:.3g} <= {marginal_p_threshold:g}, so the "
                "sources cannot explain the target's relationship to the right populations."
            )
        elif in_unit is False:
            verdict = "infeasible"
        elif p <= p_threshold:
            verdict = "marginal"
            reasons.append(
                f"Borderline fit: p = {p:.3g} is between {marginal_p_threshold:g} and "
                f"{p_threshold:g}. Conventionally this is not accepted without support "
                "from other evidence."
            )
        else:
            verdict = "plausible"
            reasons.append(
                f"The model is not rejected: p = {p:.3g} > {p_threshold:g}. The sources are "
                "consistent with the data; this does not exclude other models."
            )

    if in_unit is False:
        offenders = [
            f"{w.left}={w.weight:.3f}"
            for w in weights
            if w.weight is not None and not (-WEIGHT_TOLERANCE <= w.weight <= 1 + WEIGHT_TOLERANCE)
        ]
        reasons.append(
            "At least one admixture weight falls outside [0, 1] "
            f"({', '.join(offenders)}), which has no interpretation as an ancestry "
            "proportion and usually means a source is misspecified."
        )
        if verdict in {"plausible", "marginal"}:
            verdict = "infeasible"
    elif in_unit is None:
        reasons.append("No admixture weights were returned (qpWave-style fit or getcov=False).")

    if well_determined is False:
        loose = [
            f"{w.left}: {w.weight:.3f} +/- {w.se:.3f}"
            for w in weights
            if w.weight is not None and w.se is not None
            and w.se / max(abs(w.weight), WEIGHT_TOLERANCE) > MAX_RELATIVE_SE
        ]
        reasons.append(
            "Some weights are poorly determined — the standard error exceeds half the "
            f"estimate ({'; '.join(loose)}). The proportions should not be quoted as "
            "point estimates."
        )

    if well_conditioned is False:
        reasons.append(
            f"The f4 variance matrix is near-singular (reciprocal condition number "
            f"{f4_var_rcond:.2g}), which typically means two right populations are "
            "nearly clades, or a right population is sister to a source. Standard "
            "errors from this fit are numerically tight rather than statistically "
            "meaningful; drop or merge the offending right populations and refit."
        )

    return Feasibility(
        verdict=verdict,  # type: ignore[arg-type]
        reasons=reasons,
        p_passes=p_passes,
        weights_in_unit_interval=in_unit,
        weights_well_determined=well_determined,
        well_conditioned=well_conditioned,
        p_threshold=p_threshold,
        marginal_p_threshold=marginal_p_threshold,
        max_relative_se=MAX_RELATIVE_SE,
    )


def annotate_qpadm(
    result: QpAdmResult,
    *,
    p_threshold: float = P_PLAUSIBLE,
    marginal_p_threshold: float = P_MARGINAL,
) -> QpAdmResult:
    """Attach a :class:`Feasibility` to a qpAdm result, in place."""
    result.feasibility = assess_fit(
        p=result.p,
        weights=result.weights,
        f4_var_rcond=result.f4_var_rcond,
        p_threshold=p_threshold,
        marginal_p_threshold=marginal_p_threshold,
    )
    return result


def annotate_rotate_model(
    model: RotateModelResult,
    *,
    p_threshold: float = P_PLAUSIBLE,
    marginal_p_threshold: float = P_MARGINAL,
) -> RotateModelResult:
    """Attach a :class:`Feasibility` to one rotation model, in place."""
    model.feasibility = assess_fit(
        p=model.p,
        weights=model.weights,
        f4_var_rcond=model.f4_var_rcond,
        p_threshold=p_threshold,
        marginal_p_threshold=marginal_p_threshold,
    )
    return model


def summarize_rotation(result_models: list[RotateModelResult], *, limit: int = 5) -> str:
    """One-paragraph prose summary of a rotation run, safe to show a user."""
    total = len(result_models)
    passing = [
        m for m in result_models if m.feasibility and m.feasibility.verdict == "plausible"
    ]
    if total == 0:
        return "No models were fitted."
    if not passing:
        return (
            f"None of the {total} rotated models is consistent with the data at p > "
            f"{P_PLAUSIBLE:g} with weights in [0, 1]. Either the candidate pool is "
            "missing a necessary source, or the right set is too demanding."
        )
    shown = passing[:limit]
    parts = []
    for m in shown:
        sources = " + ".join(
            f"{w.left} {w.weight:.0%}" if w.weight is not None else str(w.left)
            for w in m.weights
        ) or " + ".join(m.left)
        parts.append(f"{sources} (p = {m.p:.3g})" if m.p is not None else sources)
    more = f", and {len(passing) - len(shown)} more" if len(passing) > len(shown) else ""
    return (
        f"{len(passing)} of {total} rotated models are consistent with the data: "
        + "; ".join(parts)
        + more
        + ". Because all of these were tested on the same SNPs, the p-values are not "
        "independent and no multiple-testing correction has been applied; several "
        "models fitting at once means the data cannot distinguish between them."
    )
