"""Tests for panel resolution against a release's group labels.

Resolution decides which populations exist at all, so a silent change here
changes every analysis downstream. Two properties are load-bearing and get a
test each: a miss on the right set must be reported (it used to be dropped),
and a miss must be classified as a rename only when the release really does
carry those individuals under another label.
"""

from __future__ import annotations

from pipeline.panel import (
    PANEL,
    PanelGroup,
    classify_unmatched,
    panel_limits,
    resolve,
)


def test_exact_and_prefix_labels_resolve() -> None:
    panel = (
        PanelGroup("block", "South Asia", ("Kalash", "Pakistan_Historic*"), "source", "Mixed"),
    )
    res = resolve(["Kalash", "Pakistan_Historic", "Pakistan_Historic_H", "Unrelated"], panel)

    assert res.group_ids == ["Kalash", "Pakistan_Historic", "Pakistan_Historic_H"]
    assert res.unmatched == []
    assert res.roles["Kalash"] == "source"


def test_a_missing_right_population_is_reported() -> None:
    """A right-set miss changes what qpAdm can resolve, so it must surface.

    It used to be dropped: the right-set loop skipped a label that matched
    nothing, so a release without a standing outgroup reported a complete
    panel. A reviewer has to see it, because it is the one miss that changes
    what the statistics can resolve rather than only what is listed.
    """
    res = resolve(["Mbuti", "Kalash"])

    assert "Han.DG" in res.unmatched_right
    assert res.classify_unmatched().missing  # and it reaches the report
    assert "Mbuti" in res.right_set


def test_right_set_survives_a_panel_block_claiming_the_role() -> None:
    """Mbuti is both a panel member and a standing outgroup."""
    res = resolve(["Mbuti"])

    assert res.roles["Mbuti"] == "context"  # the panel block wins the role
    assert "Mbuti" in res.right_set  # ... and the right set still records it


def test_a_sequencing_suffix_rename_is_not_a_gap() -> None:
    report = classify_unmatched(["Mbuti.DG", "Chimp.REF"], ["Mbuti", "Chimp"])

    assert report.missing == []
    assert report.superseded == ["Chimp.REF", "Mbuti.DG"]


def test_a_known_relabelling_is_not_a_gap() -> None:
    """v66.p1 folded the Swat Valley site labels into period labels."""
    report = classify_unmatched(["Pakistan_Butkara*"], ["Pakistan_IA"])

    assert report.superseded == ["Pakistan_Butkara*"]
    assert report.missing == []


def test_a_label_the_release_does_not_carry_is_a_gap() -> None:
    report = classify_unmatched(["Tuscan", "Mbuti.DG"], ["Mbuti", "Kalash"])

    assert report.missing == ["Tuscan"]
    assert report.superseded == ["Mbuti.DG"]


def test_a_group_the_public_aadr_cannot_carry_is_not_an_unexplained_gap() -> None:
    """Separated because the two call for different responses.

    A group AADR cannot redistribute will never arrive in a later release, so
    reporting it alongside an unexplained gap buries the handful of labels a
    maintainer should actually look at after a version bump.
    """
    report = classify_unmatched(["Onge", "Jarawa*", "Tuscan"], ["Mbuti"])

    assert report.unavailable == ["Jarawa*", "Onge"]
    assert report.missing == ["Tuscan"]
    assert report.as_dict()["unavailable_labels"] == {"Jarawa*": "consent", "Onge": "consent"}


def test_the_panel_reports_an_absent_aasi_proxy_as_a_limit() -> None:
    """The limit is what the gap costs, and it is computed, not asserted."""
    res = resolve(["Mbuti", "Kalash", "Pakistan_IA"])

    (limit,) = [lim for lim in panel_limits(res) if lim["id"] == "no_aasi_proxy"]
    assert "qpadm" in limit["affects"]
    assert "under-identified" in limit["summary"]


def test_a_resolved_aasi_proxy_clears_the_limit() -> None:
    """So the limit disappears by itself once a source supplies the proxy."""
    res = resolve(["Mbuti", "Kalash", "Onge"])

    assert [lim["id"] for lim in panel_limits(res)] == []


def test_a_rename_whose_replacement_is_also_absent_is_a_gap() -> None:
    """Being listed in RELABELLED is not enough; the replacement must resolve."""
    report = classify_unmatched(["Pakistan_Butkara*"], ["Kalash"])

    assert report.missing == ["Pakistan_Butkara*"]


def test_classification_covers_every_miss_exactly_once() -> None:
    res = resolve(["Mbuti", "Kalash", "Pakistan_IA", "Chimp"])
    report = res.classify_unmatched()

    misses = set(res.unmatched) | set(res.unmatched_right)
    buckets = [report.superseded, report.unavailable, report.missing]
    assert sum(len(b) for b in buckets) == len(misses)
    assert len(set().union(*buckets)) == len(misses)  # and none in two buckets


def test_every_relabelling_target_is_a_label_the_panel_asks_for() -> None:
    """RELABELLED must point at labels resolution actually tries to match.

    A replacement the panel never requests can never resolve, so it would
    misreport a real gap as a rename and the gap would go unnoticed.
    """
    from pipeline.panel import BASE_RIGHT, RELABELLED, _matches

    requested = {label for block in PANEL for label in block.labels} | set(BASE_RIGHT)
    for legacy, replacements in RELABELLED.items():
        for replacement in replacements:
            # A replacement may itself be a prefix pattern covering several
            # requested labels ("Turkmenistan_BA*" for "Turkmenistan_BA1-1"),
            # so match in both directions.
            covered = any(
                _matches(replacement, label) or _matches(label, replacement)
                for label in requested
            )
            assert covered, f"{legacy} -> {replacement} is not a label the panel asks for"
