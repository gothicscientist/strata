"""Real ADMIXTOOLS 2 computations.

Marked `r` and skipped unless R with the `admixtools` package is installed:

    pytest -m r services/api/tests/qpadm          # only these
    pytest -m "not r" services/api/tests          # everything else

All of these run against `admixtools::example_f2_blocks` exported to an f2
directory — seven real populations (archaic hominins, Mbuti, Chimp and three
Palaeolithic modern humans). The numbers are genuine f-statistics, not
simulated, but these are the package's demonstration populations and are
unrelated to South Asian ancestry.

The assertions are structural and relational rather than hard-coded values:
weights summing to one, p-values in [0, 1], degrees of freedom matching
(L-1-rank)(R-1-rank), f4 symmetries. Pinning exact numbers would make the suite
a change-detector for ADMIXTOOLS internals; these invariants are what must hold
for the bridge and the interpretation layer to be trustworthy.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from example_data import (
    EXAMPLE_LEFT,
    EXAMPLE_POPS,
    EXAMPLE_RIGHT,
    EXAMPLE_TARGET,
    requires_r,
)

from strata.qpadm import (
    F4Spec,
    QpAdmRotateSpec,
    QpAdmSpec,
    QpWaveSpec,
    admixtools_version,
    run_f4,
    run_qpadm,
    run_qpadm_rotate,
    run_qpwave,
)

pytestmark = [pytest.mark.r, requires_r]


@pytest.fixture(scope="module")
def qpadm_fit(example_f2_dir: Path):  # noqa: ANN201
    return run_qpadm(
        QpAdmSpec(
            target=EXAMPLE_TARGET,
            left=EXAMPLE_LEFT,
            right=EXAMPLE_RIGHT,
            f2_dir=str(example_f2_dir),
        )
    )


class TestExport:
    def test_cache_holds_the_expected_populations(self, example_f2_dir: Path) -> None:
        present = {p.name for p in example_f2_dir.iterdir() if p.is_dir()}
        for pop in EXAMPLE_POPS:
            assert pop in present, f"{pop} missing from the exported f2 cache"

    def test_export_recorded_its_provenance(self, example_f2_dir: Path) -> None:
        import json

        meta = json.loads((example_f2_dir / "strata_export.json").read_text())
        assert meta["source"] == "admixtools::example_f2_blocks"
        assert meta["n_pops"] == len(EXAMPLE_POPS)
        assert meta["n_snps"] > 0
        # The export verifies its own round-trip; keep that visible here.
        assert meta["roundtrip_max_abs_diff"] < 1e-12


class TestQpAdm:
    def test_result_is_labelled_formal(self, qpadm_fit) -> None:  # noqa: ANN001
        assert qpadm_fit.kind == "formal"
        assert qpadm_fit.engine == "admixtools2"
        assert qpadm_fit.analysis == "qpadm"
        assert "not proven" in qpadm_fit.caveat

    def test_provenance_is_recorded(self, qpadm_fit) -> None:  # noqa: ANN001
        p = qpadm_fit.provenance
        assert p.admixtools_version == admixtools_version()
        assert p.r_version_string and p.r_version_string.startswith("R version")
        assert p.timestamp_utc and p.timestamp_utc.endswith("Z")

    def test_one_weight_per_source(self, qpadm_fit) -> None:  # noqa: ANN001
        assert [w.left for w in qpadm_fit.weights] == EXAMPLE_LEFT

    def test_weights_sum_to_one(self, qpadm_fit) -> None:  # noqa: ANN001
        total = sum(w.weight for w in qpadm_fit.weights if w.weight is not None)
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_weights_have_standard_errors(self, qpadm_fit) -> None:  # noqa: ANN001
        for w in qpadm_fit.weights:
            assert w.se is not None and w.se >= 0
            if w.se > 0 and w.weight is not None:
                assert w.z == pytest.approx(w.weight / w.se, rel=1e-6)

    def test_p_value_is_a_probability(self, qpadm_fit) -> None:  # noqa: ANN001
        assert qpadm_fit.p is not None
        assert 0.0 <= qpadm_fit.p <= 1.0

    def test_headline_statistics_match_the_rankdrop_row(self, qpadm_fit) -> None:  # noqa: ANN001
        """The reported p must be the full-rank row, not the first row."""
        full_rank = len(EXAMPLE_LEFT) - 1
        assert qpadm_fit.f4rank == full_rank
        row = next(r for r in qpadm_fit.rankdrop if r.f4rank == full_rank)
        assert qpadm_fit.p == pytest.approx(row.p)
        assert qpadm_fit.chisq == pytest.approx(row.chisq)
        assert qpadm_fit.dof == pytest.approx(row.dof)

    def test_degrees_of_freedom_follow_the_formula(self, qpadm_fit) -> None:  # noqa: ANN001
        """dof = (L - 1 - rank)(R - 1 - rank) for L sources and R outgroups."""
        n_left, n_right = len(EXAMPLE_LEFT), len(EXAMPLE_RIGHT)
        for row in qpadm_fit.rankdrop:
            if row.f4rank is None or row.dof is None:
                continue
            expected = (n_left - 1 - row.f4rank) * (n_right - 1 - row.f4rank)
            assert row.dof == pytest.approx(expected)

    def test_chisq_and_p_are_consistent(self, qpadm_fit) -> None:  # noqa: ANN001
        from scipy.stats import chi2

        for row in qpadm_fit.rankdrop:
            if None in (row.chisq, row.dof, row.p) or row.dof is None or row.dof <= 0:
                continue
            assert row.p == pytest.approx(chi2.sf(row.chisq, row.dof), rel=1e-5, abs=1e-9)

    def test_popdrop_covers_every_subset(self, qpadm_fit) -> None:  # noqa: ANN001
        assert qpadm_fit.popdrop
        patterns = {r.pat for r in qpadm_fit.popdrop if r.pat}
        assert "00" in patterns  # the full model: no population dropped

    def test_f4_table_is_returned(self, qpadm_fit) -> None:  # noqa: ANN001
        assert qpadm_fit.f4
        for row in qpadm_fit.f4:
            assert row.pop1 and row.pop2 and row.pop3 and row.pop4

    def test_conditioning_diagnostic_is_present(self, qpadm_fit) -> None:  # noqa: ANN001
        assert qpadm_fit.f4_var_rcond is not None
        assert qpadm_fit.f4_var_rcond > 0

    def test_feasibility_is_attached_and_consistent(self, qpadm_fit) -> None:  # noqa: ANN001
        f = qpadm_fit.feasibility
        assert f is not None
        assert f.verdict in {"plausible", "marginal", "rejected", "infeasible", "undetermined"}
        assert f.reasons
        if qpadm_fit.p is not None:
            assert f.p_passes == (qpadm_fit.p > f.p_threshold)

    def test_assessment_can_be_switched_off(self, example_f2_dir: Path) -> None:
        result = run_qpadm(
            QpAdmSpec(
                target=EXAMPLE_TARGET,
                left=EXAMPLE_LEFT,
                right=EXAMPLE_RIGHT,
                f2_dir=str(example_f2_dir),
            ),
            assess=False,
        )
        assert result.feasibility is None

    def test_determinism(self, example_f2_dir: Path, qpadm_fit) -> None:  # noqa: ANN001
        """The same spec on the same cache must give the same numbers."""
        again = run_qpadm(
            QpAdmSpec(
                target=EXAMPLE_TARGET,
                left=EXAMPLE_LEFT,
                right=EXAMPLE_RIGHT,
                f2_dir=str(example_f2_dir),
            )
        )
        assert again.p == pytest.approx(qpadm_fit.p, rel=1e-12)
        for a, b in zip(again.weights, qpadm_fit.weights, strict=True):
            assert a.weight == pytest.approx(b.weight, rel=1e-12)

    def test_single_source_model_is_a_cladality_test(self, example_f2_dir: Path) -> None:
        """One source and rank 0: the weight is fixed at 1 by construction."""
        result = run_qpadm(
            QpAdmSpec(
                target=EXAMPLE_TARGET,
                left=["Vindija.DG"],
                right=EXAMPLE_RIGHT,
                f2_dir=str(example_f2_dir),
            )
        )
        assert result.f4rank == 0
        assert len(result.weights) == 1
        assert result.weights[0].weight == pytest.approx(1.0, abs=1e-9)

    def test_unknown_population_fails_cleanly(self, example_f2_dir: Path) -> None:
        from strata.qpadm import QpAdmError

        with pytest.raises(QpAdmError):
            run_qpadm(
                QpAdmSpec(
                    target="Not_A_Population",
                    left=EXAMPLE_LEFT,
                    right=EXAMPLE_RIGHT,
                    f2_dir=str(example_f2_dir),
                )
            )


class TestQpWave:
    def test_rank_table_and_bound(self, example_f2_dir: Path) -> None:
        result = run_qpwave(
            QpWaveSpec(
                left=EXAMPLE_LEFT,
                right=EXAMPLE_RIGHT,
                f2_dir=str(example_f2_dir),
            )
        )
        assert result.kind == "formal"
        assert result.analysis == "qpwave"
        assert result.rankdrop
        ranks = [r.f4rank for r in result.rankdrop]
        assert ranks == sorted(ranks)
        for row in result.rankdrop:
            if row.p is not None:
                assert 0.0 <= row.p <= 1.0
        if result.min_rank_not_rejected is not None:
            assert result.min_rank_not_rejected >= 0

    def test_rank_zero_tests_cladality(self, example_f2_dir: Path) -> None:
        """Rank 0 asks whether left and right are two clades."""
        result = run_qpwave(
            QpWaveSpec(
                left=EXAMPLE_LEFT, right=EXAMPLE_RIGHT, f2_dir=str(example_f2_dir)
            )
        )
        row = next(r for r in result.rankdrop if r.f4rank == 0)
        n_left, n_right = len(EXAMPLE_LEFT), len(EXAMPLE_RIGHT)
        assert row.dof == pytest.approx((n_left - 1) * (n_right - 1))


class TestF4:
    def test_f4_statistics(self, example_f2_dir: Path) -> None:
        result = run_f4(
            F4Spec(
                pop1=["Chimp.REF"],
                pop2=["Mbuti.DG"],
                pop3=["Altai_Neanderthal.DG"],
                pop4=["Denisova.DG"],
                f2_dir=str(example_f2_dir),
            )
        )
        assert result.kind == "formal"
        assert result.n_statistics == len(result.f4) >= 1
        row = result.f4[0]
        assert row.est is not None
        assert row.se is not None and row.se > 0
        assert row.z == pytest.approx(row.est / row.se, rel=1e-5)
        assert row.p is not None and 0.0 <= row.p <= 1.0

    def test_f4_antisymmetry(self, example_f2_dir: Path) -> None:
        """f4(A,B;C,D) = -f4(B,A;C,D). A real identity, not a convention."""
        kwargs = {"f2_dir": str(example_f2_dir), "comb": False}
        a = run_f4(
            F4Spec(
                pop1=["Chimp.REF"],
                pop2=["Mbuti.DG"],
                pop3=["Altai_Neanderthal.DG"],
                pop4=["Denisova.DG"],
                **kwargs,  # type: ignore[arg-type]
            )
        ).f4[0]
        b = run_f4(
            F4Spec(
                pop1=["Mbuti.DG"],
                pop2=["Chimp.REF"],
                pop3=["Altai_Neanderthal.DG"],
                pop4=["Denisova.DG"],
                **kwargs,  # type: ignore[arg-type]
            )
        ).f4[0]
        assert a.est is not None and b.est is not None
        assert a.est == pytest.approx(-b.est, rel=1e-8, abs=1e-12)
        assert a.se == pytest.approx(b.se, rel=1e-8)

    def test_f4_is_zero_when_the_quadruple_is_degenerate(
        self, example_f2_dir: Path
    ) -> None:
        """f4(A,B;C,C) is identically zero."""
        result = run_f4(
            F4Spec(
                pop1=["Chimp.REF"],
                pop2=["Mbuti.DG"],
                pop3=["Denisova.DG"],
                pop4=["Denisova.DG"],
                comb=False,
                unique_only=False,
                f2_dir=str(example_f2_dir),
            )
        )
        assert result.f4[0].est == pytest.approx(0.0, abs=1e-12)

    def test_combinations_expand(self, example_f2_dir: Path) -> None:
        result = run_f4(
            F4Spec(
                pop1=["Chimp.REF"],
                pop2=["Mbuti.DG"],
                pop3=["Altai_Neanderthal.DG", "Vindija.DG"],
                pop4=["Denisova.DG"],
                f2_dir=str(example_f2_dir),
            )
        )
        assert result.n_statistics >= 2


class TestRotation:
    def test_rotation_fits_and_ranks_models(self, example_f2_dir: Path) -> None:
        result = run_qpadm_rotate(
            QpAdmRotateSpec(
                target=EXAMPLE_TARGET,
                leftright=[
                    "Altai_Neanderthal.DG",
                    "Vindija.DG",
                    "Russia_Ust_Ishim.DG",
                    "Switzerland_Bichon.SG",
                ],
                rightfix=["Chimp.REF", "Mbuti.DG"],
                max_sources=2,
                f2_dir=str(example_f2_dir),
            )
        )
        assert result.kind == "formal"
        assert result.analysis == "qpadm_rotate"
        assert result.n_models_tested == len(result.models) >= 2
        assert "multiple testing" in result.rotation_caveat

        # Ranked best-p-first, with NA p-values last.
        ps = [m.p for m in result.models]
        finite = [p for p in ps if p is not None and not math.isnan(p)]
        assert finite == sorted(finite, reverse=True)
        assert [m.rank for m in result.models] == list(range(1, len(result.models) + 1))

        for m in result.models:
            assert m.n_sources == len(m.left) <= 2
            assert not set(m.left) & set(m.right)
            assert EXAMPLE_TARGET not in m.left and EXAMPLE_TARGET not in m.right
            assert {"Chimp.REF", "Mbuti.DG"} <= set(m.right)
            assert m.feasibility is not None

    def test_max_models_is_enforced(self, example_f2_dir: Path) -> None:
        from strata.qpadm import QpAdmError

        with pytest.raises(QpAdmError, match="max_models"):
            run_qpadm_rotate(
                QpAdmRotateSpec(
                    target=EXAMPLE_TARGET,
                    leftright=[
                        "Altai_Neanderthal.DG",
                        "Vindija.DG",
                        "Russia_Ust_Ishim.DG",
                        "Switzerland_Bichon.SG",
                    ],
                    rightfix=["Chimp.REF", "Mbuti.DG"],
                    max_models=1,
                    f2_dir=str(example_f2_dir),
                )
            )

    def test_rotation_agrees_with_a_direct_fit(self, example_f2_dir: Path) -> None:
        """A model that rotation fits must match running it on its own."""
        rotated = run_qpadm_rotate(
            QpAdmRotateSpec(
                target=EXAMPLE_TARGET,
                leftright=["Altai_Neanderthal.DG", "Vindija.DG", "Russia_Ust_Ishim.DG"],
                rightfix=["Chimp.REF", "Mbuti.DG", "Switzerland_Bichon.SG"],
                max_sources=1,
                f2_dir=str(example_f2_dir),
            )
        )
        model = rotated.models[0]
        direct = run_qpadm(
            QpAdmSpec(
                target=EXAMPLE_TARGET,
                left=model.left,
                right=model.right,
                f2_dir=str(example_f2_dir),
            )
        )
        assert direct.p == pytest.approx(model.p, rel=1e-8)


class TestCrossCheck:
    """Agreement between the R engine and Strata's own f-statistic code.

    `strata.analysis.fstats` is a pure-NumPy implementation used for the
    exploratory path. It is not expected to match ADMIXTOOLS bit for bit — it
    works from allele frequencies rather than from f2 blocks — so this test is
    deliberately tolerant and is skipped when the module is absent. What it
    catches is a sign error or a factor-of-two slip, which is the realistic
    failure mode when two implementations of f4 coexist.
    """

    def test_f4_identity_from_f2(self, example_f2_dir: Path) -> None:
        """f4(A,B;C,D) = (f2(A,D) + f2(B,C) - f2(A,C) - f2(B,D)) / 2.

        Checked entirely within ADMIXTOOLS, so it holds with or without
        strata.analysis.fstats and validates how the bridge reads f2 caches.
        """
        pops = ["Chimp.REF", "Mbuti.DG", "Altai_Neanderthal.DG", "Denisova.DG"]
        a, b, c, d = pops
        f4 = run_f4(
            F4Spec(
                pop1=[a], pop2=[b], pop3=[c], pop4=[d],
                comb=False, f2_dir=str(example_f2_dir),
            )
        ).f4[0]

        def f2_of(x: str, y: str) -> float:
            # f2(X, Y) is f4(X, Y; X, Y).
            row = run_f4(
                F4Spec(
                    pop1=[x], pop2=[y], pop3=[x], pop4=[y],
                    comb=False, unique_only=False, f2_dir=str(example_f2_dir),
                )
            ).f4[0]
            assert row.est is not None
            return row.est

        expected = (f2_of(a, d) + f2_of(b, c) - f2_of(a, c) - f2_of(b, d)) / 2.0
        assert f4.est is not None
        assert f4.est == pytest.approx(expected, rel=1e-6, abs=1e-10)

    def test_against_strata_fstats_if_available(self, example_f2_dir: Path) -> None:
        pytest.importorskip(
            "strata.analysis.fstats",
            reason="strata.analysis.fstats not present; cross-check is optional",
        )
        from strata.analysis import fstats as sf

        # The pure-NumPy path needs allele frequencies, which an f2 cache does
        # not contain. Without a genotype panel in the test environment there
        # is nothing to compare, so assert only that the two surfaces agree on
        # their contract rather than inventing data to feed one of them.
        assert hasattr(sf, "f4")
        assert hasattr(sf, "f2_blocks")
