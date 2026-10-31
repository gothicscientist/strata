"""Spec validation and feasibility interpretation. No R required."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from strata.qpadm import (
    FORMAL_CAVEAT,
    ROTATION_CAVEAT,
    ExtractF2Spec,
    F4Spec,
    QpAdmResult,
    QpAdmRotateSpec,
    QpAdmSpec,
    QpWaveSpec,
    RotateModelResult,
    WeightRow,
    assess_fit,
    summarize_rotation,
)
from strata.qpadm.interpret import annotate_rotate_model


def spec(**over: object) -> QpAdmSpec:
    base: dict[str, object] = {
        "target": "T",
        "left": ["A", "B"],
        "right": ["R1", "R2", "R3"],
        "f2_dir": "/tmp/f2",
    }
    base.update(over)
    return QpAdmSpec(**base)  # type: ignore[arg-type]


class TestQpAdmSpec:
    def test_minimal_spec(self) -> None:
        s = spec()
        assert s.data_source == "f2_dir"
        assert s.blgsize == 0.05

    def test_requires_exactly_one_data_source(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            QpAdmSpec(target="T", left=["A"], right=["R1", "R2"])
        with pytest.raises(ValidationError, match="exactly one"):
            QpAdmSpec(
                target="T",
                left=["A"],
                right=["R1", "R2"],
                f2_dir="/a",
                geno_prefix="/b",
            )

    def test_target_may_not_be_a_source(self) -> None:
        with pytest.raises(ValidationError, match="not also appear in 'left'"):
            spec(left=["T", "B"])

    def test_target_may_not_be_an_outgroup(self) -> None:
        with pytest.raises(ValidationError, match="not also appear in 'right'"):
            spec(right=["T", "R2", "R3"])

    def test_sides_must_be_disjoint(self) -> None:
        with pytest.raises(ValidationError, match="both sides"):
            spec(left=["A", "R1"])

    def test_needs_more_right_than_left(self) -> None:
        """qpAdm cannot fit a model without more outgroups than sources."""
        with pytest.raises(ValidationError, match="more right than left"):
            spec(left=["A", "B"], right=["R1", "R2"])

    def test_rejects_duplicates(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            spec(left=["A", "A"])
        with pytest.raises(ValidationError, match="duplicate"):
            spec(right=["R1", "R1", "R2"])

    def test_right_needs_at_least_two(self) -> None:
        with pytest.raises(ValidationError):
            spec(left=["A"], right=["R1"])

    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            spec(nonsense=True)

    def test_boot_integer_must_be_sensible(self) -> None:
        with pytest.raises(ValidationError, match="boot"):
            spec(boot=1)
        assert spec(boot=100).boot == 100
        assert spec(boot=True).boot is True

    def test_maxmiss_bounds(self) -> None:
        with pytest.raises(ValidationError):
            spec(maxmiss=1.5)
        assert spec(maxmiss=0.5).maxmiss == 0.5

    def test_serialises_without_unset_optionals(self) -> None:
        payload = spec().model_dump(mode="json", exclude_none=True)
        assert "geno_prefix" not in payload
        assert "maxmiss" not in payload
        assert payload["f2_dir"] == "/tmp/f2"


class TestRotateSpec:
    def test_accepts_api_aliases(self) -> None:
        """The API and agent layers send `candidates` / `right`."""
        s = QpAdmRotateSpec(
            target="T",
            candidates=["A", "B", "C"],
            right=["O1", "O2"],
            f2_dir="/tmp/f2",
        )
        assert s.leftright == ["A", "B", "C"]
        assert s.rightfix == ["O1", "O2"]

    def test_canonical_names_also_work(self) -> None:
        s = QpAdmRotateSpec(
            target="T", leftright=["A", "B"], rightfix=["O1"], f2_dir="/tmp/f2"
        )
        assert s.leftright == ["A", "B"]

    def test_target_not_in_pool(self) -> None:
        with pytest.raises(ValidationError, match="not appear in 'leftright'"):
            QpAdmRotateSpec(target="T", leftright=["T", "B"], f2_dir="/tmp/f2")

    def test_pool_and_rightfix_disjoint(self) -> None:
        with pytest.raises(ValidationError, match="both"):
            QpAdmRotateSpec(
                target="T", leftright=["A", "B"], rightfix=["A"], f2_dir="/tmp/f2"
            )

    def test_max_sources_at_least_min(self) -> None:
        with pytest.raises(ValidationError, match="max_sources"):
            QpAdmRotateSpec(
                target="T",
                leftright=["A", "B"],
                min_sources=3,
                max_sources=2,
                f2_dir="/tmp/f2",
            )


class TestOtherSpecs:
    def test_qpwave_sides_disjoint(self) -> None:
        with pytest.raises(ValidationError, match="both sides"):
            QpWaveSpec(left=["A", "B"], right=["B", "C"], f2_dir="/tmp/f2")

    def test_f4_zipped_mode_needs_equal_lengths(self) -> None:
        with pytest.raises(ValidationError, match="same length"):
            F4Spec(
                pop1=["A"],
                pop2=["B", "C"],
                pop3=["D"],
                pop4=["E"],
                comb=False,
                f2_dir="/tmp/f2",
            )

    def test_dstatistics_require_genotypes(self) -> None:
        """D-statistics cannot be computed from precomputed f2 blocks."""
        with pytest.raises(ValidationError, match="geno_prefix"):
            F4Spec(
                pop1=["A"],
                pop2=["B"],
                pop3=["C"],
                pop4=["D"],
                f4mode=False,
                f2_dir="/tmp/f2",
            )
        ok = F4Spec(
            pop1=["A"], pop2=["B"], pop3=["C"], pop4=["D"], f4mode=False, geno_prefix="/p"
        )
        assert ok.data_source == "geno_prefix"

    def test_extract_f2_pops_and_inds_must_align(self) -> None:
        with pytest.raises(ValidationError, match="same length"):
            ExtractF2Spec(
                geno_prefix="/p", out_dir="/o", pops=["A", "B"], inds=["i1"]
            )

    def test_extract_f2_allows_grouping_several_inds_into_one_pop(self) -> None:
        s = ExtractF2Spec(
            geno_prefix="/p", out_dir="/o", pops=["A", "A"], inds=["i1", "i2"]
        )
        assert s.pops == ["A", "A"]

    def test_extract_f2_rejects_duplicate_pops_without_inds(self) -> None:
        with pytest.raises(ValidationError, match="duplicates"):
            ExtractF2Spec(geno_prefix="/p", out_dir="/o", pops=["A", "A"])

    def test_extract_f2_rejects_excluding_all_sites(self) -> None:
        with pytest.raises(ValidationError, match="both transitions"):
            ExtractF2Spec(
                geno_prefix="/p", out_dir="/o", transitions=False, transversions=False
            )


def weights(*pairs: tuple[str, float, float | None]) -> list[WeightRow]:
    return [WeightRow(left=n, weight=w, se=s) for n, w, s in pairs]


class TestFeasibility:
    def test_plausible_model(self) -> None:
        f = assess_fit(p=0.42, weights=weights(("A", 0.3, 0.02), ("B", 0.7, 0.02)))
        assert f.verdict == "plausible"
        assert f.p_passes is True
        assert f.weights_in_unit_interval is True
        assert any("not rejected" in r for r in f.reasons)

    def test_marginal_model(self) -> None:
        f = assess_fit(p=0.03, weights=weights(("A", 0.4, 0.02), ("B", 0.6, 0.02)))
        assert f.verdict == "marginal"
        assert f.p_passes is False

    def test_rejected_model(self) -> None:
        f = assess_fit(p=1e-6, weights=weights(("A", 0.5, 0.02), ("B", 0.5, 0.02)))
        assert f.verdict == "rejected"

    def test_negative_weight_is_infeasible(self) -> None:
        f = assess_fit(p=0.5, weights=weights(("A", -0.2, 0.05), ("B", 1.2, 0.05)))
        assert f.verdict == "infeasible"
        assert f.weights_in_unit_interval is False
        assert any("outside [0, 1]" in r for r in f.reasons)

    def test_rejection_takes_precedence_over_infeasibility(self) -> None:
        """A rejected model is rejected regardless of its weights."""
        f = assess_fit(p=1e-9, weights=weights(("A", -0.5, 0.05)))
        assert f.verdict == "rejected"

    def test_tiny_numerical_overshoot_is_tolerated(self) -> None:
        f = assess_fit(p=0.5, weights=weights(("A", 1.0 + 1e-9, 0.01)))
        assert f.weights_in_unit_interval is True

    def test_missing_p_is_undetermined(self) -> None:
        f = assess_fit(p=None, weights=weights(("A", 0.5, 0.01)))
        assert f.verdict == "undetermined"
        assert f.p_passes is None

    def test_nan_p_is_undetermined(self) -> None:
        f = assess_fit(p=float("nan"), weights=weights(("A", 0.5, 0.01)))
        assert f.verdict == "undetermined"

    def test_large_standard_errors_are_flagged(self) -> None:
        f = assess_fit(p=0.5, weights=weights(("A", 0.1, 0.4), ("B", 0.9, 0.05)))
        assert f.verdict == "plausible"
        assert f.weights_well_determined is False
        assert any("poorly determined" in r for r in f.reasons)

    def test_singular_f4_variance_is_flagged(self) -> None:
        f = assess_fit(
            p=0.9, weights=weights(("A", 0.5, 0.001)), f4_var_rcond=1e-16
        )
        assert f.well_conditioned is False
        assert any("near-singular" in r for r in f.reasons)

    def test_well_conditioned_passes(self) -> None:
        f = assess_fit(p=0.5, weights=weights(("A", 0.5, 0.02)), f4_var_rcond=1e-3)
        assert f.well_conditioned is True

    def test_no_weights_is_reported(self) -> None:
        f = assess_fit(p=0.5, weights=[])
        assert f.weights_in_unit_interval is None
        assert any("No admixture weights" in r for r in f.reasons)

    def test_nan_standard_errors_are_ignored(self) -> None:
        f = assess_fit(p=0.5, weights=[WeightRow(left="A", weight=0.5, se=None)])
        assert f.weights_well_determined is None

    def test_thresholds_are_configurable_and_ordered(self) -> None:
        f = assess_fit(
            p=0.2, weights=weights(("A", 0.5, 0.01)), p_threshold=0.3
        )
        assert f.verdict == "marginal"
        with pytest.raises(ValueError, match="must be <="):
            assess_fit(
                p=0.5,
                weights=weights(("A", 0.5, 0.01)),
                p_threshold=0.01,
                marginal_p_threshold=0.05,
            )

    def test_note_disclaims_model_selection(self) -> None:
        f = assess_fit(p=0.5, weights=weights(("A", 0.5, 0.01)))
        assert "not a formal model-selection procedure" in f.note
        assert "does not mean the model" in f.note


class TestResultLabelling:
    def test_qpadm_result_is_formal(self) -> None:
        r = QpAdmResult(
            target="T", left=["A"], right=["R1", "R2"], data_source="f2_dir"
        )
        assert r.kind == "formal"
        assert r.engine == "admixtools2"
        assert r.caveat == FORMAL_CAVEAT
        assert "not proven" in r.caveat

    def test_unknown_table_columns_are_kept(self) -> None:
        """A future ADMIXTOOLS column must not fail validation."""
        row = WeightRow.model_validate(
            {"left": "A", "weight": 0.5, "se": 0.1, "brand_new_column": 7}
        )
        assert row.left == "A"
        assert row.model_extra == {"brand_new_column": 7}


class TestRotationSummary:
    def _model(self, index: int, p: float, w: float) -> RotateModelResult:
        m = RotateModelResult(
            model_index=index,
            left=["A", "B"],
            right=["R1", "R2", "R3"],
            n_sources=2,
            p=p,
            weights=weights(("A", w, 0.02), ("B", 1 - w, 0.02)),
        )
        return annotate_rotate_model(m)

    def test_reports_multiple_testing(self) -> None:
        models = [self._model(1, 0.6, 0.4), self._model(2, 0.2, 0.5)]
        text = summarize_rotation(models)
        assert "2 of 2" in text
        assert "not independent" in text
        assert "no multiple-testing correction" in text

    def test_no_passing_models_is_stated_plainly(self) -> None:
        models = [self._model(1, 1e-8, 0.4)]
        text = summarize_rotation(models)
        assert "None of the 1" in text

    def test_empty_rotation(self) -> None:
        assert summarize_rotation([]) == "No models were fitted."

    def test_rotation_caveat_is_attached_to_results(self) -> None:
        assert "multiple testing" in ROTATION_CAVEAT

