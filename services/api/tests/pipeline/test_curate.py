"""Tests for QC, panel resolution and population assembly.

Every exclusion rule here changes which individuals end up in an f2 cache, and
therefore changes every p-value computed from it, so each rule gets a test that
would fail if the rule silently stopped firing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pipeline.anno import AnnoRecord, read_anno
from pipeline.config import QcThresholds
from pipeline.curate import (
    CuratedSample,
    assessment_is_ok,
    build_populations,
    curate_samples,
    f2_eligible,
    group_is_usable,
    infer_period,
    slugify,
)
from pipeline.panel import PanelGroup, resolve


@pytest.fixture
def records(mini_anno: Path) -> list[AnnoRecord]:
    return read_anno(mini_anno)


class TestSlugify:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Russia_Sintashta_MLBA", "russia-sintashta-mlba"),
            ("Onge.DG", "onge-dg"),
            ("Ju_hoan_North.DG", "ju-hoan-north-dg"),
            ("I2657", "i2657"),
            ("!!!", "unknown"),
        ],
    )
    def test_slugs(self, raw: str, expected: str) -> None:
        assert slugify(raw) == expected


class TestGroupUsable:
    @pytest.mark.parametrize(
        "group",
        [
            "Ignore_Synthetica_IA_dup.SYN001",
            "Pakistan_Swat_IA_contam",
            "India_X_lc",
            "Synthetica_IA_1d_rel.SYN001",
            "Russia_Y_published",
        ],
    )
    def test_rejected(self, group: str) -> None:
        usable, reason = group_is_usable(group)
        assert usable is False
        assert reason

    @pytest.mark.parametrize(
        "group",
        [
            "Synthetica_IA",
            "Iran_ShahrISokhta_BA2",
            "Pakistan_SwatValleyProtohistoric_IA_outlier",
            "India_Roopkund_A",
            "Onge.DG",
        ],
    )
    def test_accepted(self, group: str) -> None:
        usable, reason = group_is_usable(group)
        assert usable is True, reason

    def test_outlier_groups_are_real_analysis_units(self) -> None:
        """AADR's `_outlier` labels are usable groups, unlike `_contam`/`_rel`."""
        assert group_is_usable("Iran_ShahrISokhta_BA_outlier")[0] is True
        assert group_is_usable("Iran_ShahrISokhta_BA_outlier2")[0] is True


class TestAssessment:
    def test_pass_accepted(self) -> None:
        rec = AnnoRecord(genetic_id="X", group_id="P", assessment="PASS", date_mean_bp=3000)
        assert assessment_is_ok(rec)[0] is True

    @pytest.mark.parametrize(
        ("assessment", "warnings"),
        [
            ("QUESTIONABLE", None),
            ("QUESTIONABLE_CRITICAL", None),
            ("FAIL", None),
            ("PASS", "Xcontam 0.015-0.021 (QUESTIONABLE)"),
            ("PASS", "FAIL"),
        ],
    )
    def test_contamination_rejected(self, assessment: str, warnings: str | None) -> None:
        rec = AnnoRecord(
            genetic_id="X",
            group_id="P",
            assessment=assessment,
            assessment_warnings=warnings,
            date_mean_bp=3000,
        )
        ok, reason = assessment_is_ok(rec)
        assert ok is False
        assert reason

    def test_missing_assessment_rejected_for_ancient(self) -> None:
        rec = AnnoRecord(genetic_id="X", group_id="P", date_mean_bp=3000)
        ok, reason = assessment_is_ok(rec)
        assert ok is False
        assert reason == "assessment_missing"

    def test_missing_assessment_allowed_for_present_day(self) -> None:
        """Present-day array data carries no ancient-DNA quality verdict."""
        rec = AnnoRecord(genetic_id="X", group_id="P", date_mean_bp=0.0)
        assert assessment_is_ok(rec)[0] is True


class TestCurateSamples:
    def test_fixture_exclusions(self, records: list[AnnoRecord]) -> None:
        kept, log = curate_samples(records, snpset="1240K")
        kept_ids = {s.id for s in kept}
        assert kept_ids == {"SYN001", "SYN002", "SYN005", "SYN006", "SYN007", "SYN010", "SYN011"}
        reasons = log.counts
        assert reasons["low_coverage"] == 1  # SYN003, 12,004 SNPs
        assert reasons["group_ignored"] == 1  # SYN008
        assert reasons["assessment_fail"] == 1  # SYN012
        assert sum(reasons.values()) == 5

    def test_low_coverage_threshold_is_applied(self, records: list[AnnoRecord]) -> None:
        strict = QcThresholds(min_snps=600_000, min_snps_modern=0)
        kept, log = curate_samples(records, snpset="1240K", qc=strict)
        # SYN002 has 98,765 SNPs on 1240K and now falls below the bar.
        assert "SYN002" not in {s.id for s in kept}
        assert log.counts["low_coverage"] >= 2

    def test_snpset_choice_changes_the_coverage_filter(self, records: list[AnnoRecord]) -> None:
        """HO counts are ~half the 1240K counts, so the same bar excludes more."""
        qc = QcThresholds(min_snps=500_000, min_snps_modern=0)
        kept_1240k = {s.id for s in curate_samples(records, snpset="1240K", qc=qc)[0]}
        kept_ho = {s.id for s in curate_samples(records, snpset="HO", qc=qc)[0]}
        assert "SYN002" not in kept_ho
        assert kept_ho != kept_1240k

    def test_duplicate_master_id_keeps_highest_coverage(self) -> None:
        recs = [
            AnnoRecord(
                genetic_id="A1",
                group_id="PopA",
                master_id="M1",
                assessment="PASS",
                date_mean_bp=3000,
                n_snps_1240k=400_000,
            ),
            AnnoRecord(
                genetic_id="A2",
                group_id="PopA",
                master_id="M1",
                assessment="PASS",
                date_mean_bp=3000,
                n_snps_1240k=900_000,
            ),
        ]
        kept, log = curate_samples(recs, snpset="1240K")
        assert [s.id for s in kept] == ["A2"]
        assert log.counts["duplicate_master_id"] == 1

    def test_deduplication_can_be_disabled(self) -> None:
        recs = [
            AnnoRecord(
                genetic_id=f"A{i}",
                group_id="PopA",
                master_id="M1",
                assessment="PASS",
                date_mean_bp=3000,
                n_snps_1240k=400_000 + i,
            )
            for i in (1, 2)
        ]
        qc = QcThresholds(deduplicate_on_master_id=False)
        kept, _ = curate_samples(recs, snpset="1240K", qc=qc)
        assert len(kept) == 2

    def test_keep_groups_restricts_to_panel(self, records: list[AnnoRecord]) -> None:
        kept, log = curate_samples(records, snpset="1240K", keep_groups={"Synthetica_IA"})
        assert {s.group_id for s in kept} == {"Synthetica_IA"}
        assert log.counts["not_in_panel"] > 0

    def test_present_day_without_snp_count_is_kept(self) -> None:
        """HO present-day rows have no 1240K SNP count; they must survive."""
        rec = AnnoRecord(
            genetic_id="M1", group_id="Modernia", date_mean_bp=0.0, assessment="PASS"
        )
        kept, log = curate_samples([rec], snpset="1240K")
        assert [s.id for s in kept] == ["M1"]
        assert log.counts["snp_count_missing"] == 0

    def test_ancient_without_snp_count_is_dropped(self) -> None:
        rec = AnnoRecord(
            genetic_id="A1", group_id="PopA", date_mean_bp=3000, assessment="PASS"
        )
        kept, log = curate_samples([rec], snpset="1240K")
        assert kept == []
        assert log.counts["snp_count_missing"] == 1

    def test_output_order_is_deterministic(self, records: list[AnnoRecord]) -> None:
        a = [s.id for s in curate_samples(records, snpset="1240K")[0]]
        b = [s.id for s in curate_samples(records, snpset="1240K")[0]]
        assert a == b

    def test_pseudohaploid_flag_tracks_antiquity(self, records: list[AnnoRecord]) -> None:
        kept, _ = curate_samples(records, snpset="1240K")
        by_id = {s.id: s for s in kept}
        assert by_id["SYN001"].pseudohaploid is True
        assert by_id["SYN006"].pseudohaploid is False

    def test_exclusion_log_serialises(self, records: list[AnnoRecord]) -> None:
        _, log = curate_samples(records, snpset="1240K")
        payload = log.as_dict()
        assert payload["total_excluded"] == 5
        assert set(payload["by_reason"]) == set(payload["examples"])


class TestPeriods:
    @pytest.mark.parametrize(
        ("bp", "expected"),
        [
            (None, "Modern"),
            (0, "Modern"),
            (300, "Early Modern"),
            (1000, "Medieval"),
            (2200, "Iron Age"),
            (3500, "Bronze Age"),
            (5000, "Chalcolithic"),
            (9000, "Neolithic"),
            (11000, "Mesolithic"),
            (30000, "Upper Palaeolithic"),
        ],
    )
    def test_period_bands(self, bp: float | None, expected: str) -> None:
        assert infer_period(bp, is_present_day=False) == expected

    def test_present_day_overrides_date(self) -> None:
        assert infer_period(3000, is_present_day=True) == "Modern"


class TestBuildPopulations:
    def test_aggregates_members(self, records: list[AnnoRecord]) -> None:
        kept, _ = curate_samples(records, snpset="1240K")
        pops, _ = build_populations(kept, data_source="AADR-test")
        by_id = {p.group_id: p for p in pops}
        ia = by_id["Synthetica_IA"]
        assert ia.n_samples == 2
        assert ia.date_mean_bp == pytest.approx(3175.0)
        assert ia.date_min_bp == 3150.0
        assert ia.date_max_bp == 3200.0
        assert ia.lat == pytest.approx(34.5)
        assert ia.id == "synthetica-ia"

    def test_modern_population_is_labelled_modern(self, records: list[AnnoRecord]) -> None:
        kept, _ = curate_samples(records, snpset="1240K")
        pops, _ = build_populations(kept, data_source="AADR-test")
        modernia = next(p for p in pops if p.group_id == "Modernia")
        assert modernia.period == "Modern"
        assert modernia.n_samples == 2

    def test_min_population_size_drops_and_logs(self, records: list[AnnoRecord]) -> None:
        kept, _ = curate_samples(records, snpset="1240K")
        qc = QcThresholds(min_population_size=2)
        pops, log = build_populations(kept, data_source="AADR-test", qc=qc)
        sizes = {p.n_samples for p in pops}
        assert min(sizes) >= 2
        assert log.counts["population_too_small"] > 0

    def test_spaces_propagate(self, records: list[AnnoRecord]) -> None:
        kept, _ = curate_samples(records, snpset="1240K")
        pops, _ = build_populations(kept, data_source="AADR-test", spaces=["strata-pca-v1"])
        assert all(p.spaces == ["strata-pca-v1"] for p in pops)

    def test_f2_eligible_filters_by_size(self) -> None:
        samples = [
            CuratedSample(
                id=f"S{i}",
                population_id="p",
                group_id="PopA" if i < 3 else "PopB",
                master_id=None,
                sex="U",
                date_mean_bp=3000,
                date_sd=None,
                lat=None,
                lon=None,
                country=None,
                locality=None,
                data_type=None,
                n_snps=500_000,
                pseudohaploid=True,
                publication_id=None,
                assessment="PASS",
                is_present_day=False,
            )
            for i in range(4)
        ]
        pops, _ = build_populations(samples, data_source="t")
        eligible = f2_eligible(pops, QcThresholds(min_population_size_for_f2=3))
        assert {p.group_id for p in eligible} == {"PopA"}


class TestPanelResolution:
    def test_exact_and_prefix_matching(self) -> None:
        panel = (
            PanelGroup("block", "Region", ("Onge.DG", "Pakistan_Swat*"), "source", "Mixed"),
        )
        available = [
            "Onge.DG",
            "Pakistan_SwatValleyProtohistoric_IA",
            "Pakistan_Swat_H",
            "France_Unrelated",
        ]
        res = resolve(available, panel)
        assert set(res.group_ids) == {
            "Onge.DG",
            "Pakistan_SwatValleyProtohistoric_IA",
            "Pakistan_Swat_H",
        }
        assert res.unmatched == []

    def test_unmatched_labels_are_reported_not_fatal(self) -> None:
        panel = (PanelGroup("block", "Region", ("Nonexistent_Group",), "source", "Mixed"),)
        # Kalash.DG is not in the standing right set, so nothing should claim it.
        res = resolve(["Kalash.DG"], panel)
        assert res.group_ids == []
        assert res.unmatched == ["Nonexistent_Group"]

    def test_roles_are_assigned(self) -> None:
        panel = (PanelGroup("b", "R", ("Kalash.DG",), "target_cline", "Modern"),)
        res = resolve(["Kalash.DG", "Mbuti.DG"], panel)
        # Mbuti.DG is in the project's fixed right set.
        assert res.roles["Mbuti.DG"] == "right"
        assert res.roles["Kalash.DG"] == "target_cline"

    def test_panel_block_role_beats_the_standing_right_role(self) -> None:
        """Onge.DG is both the AASI proxy and a conventional outgroup.

        The explicit panel role must win, or the population silently becomes an
        outgroup in models that were meant to use it as a source.
        """
        panel = (PanelGroup("b", "R", ("Onge.DG",), "target_cline", "Modern"),)
        res = resolve(["Onge.DG"], panel)
        assert res.roles["Onge.DG"] == "target_cline"
        assert res.matched["Onge.DG"] == "b"

    def test_real_panel_resolves_known_labels(self) -> None:
        available = [
            "Iran_ShahrISokhta_BA2",
            "Pakistan_SwatValleyProtohistoric_IA",
            "India_Roopkund_A",
            "Russia_Sintashta_MLBA1",
            "Iran_GanjDareh_N",
            "Onge.DG",
            "Kalash.DG",
            "Mbuti.DG",
            "Totally_Unrelated_Group",
        ]
        res = resolve(available)
        assert "Totally_Unrelated_Group" not in res.matched
        for expected in (
            "Iran_ShahrISokhta_BA2",
            "Pakistan_SwatValleyProtohistoric_IA",
            "India_Roopkund_A",
            "Russia_Sintashta_MLBA1",
            "Iran_GanjDareh_N",
            "Onge.DG",
            "Kalash.DG",
        ):
            assert expected in res.matched, expected
