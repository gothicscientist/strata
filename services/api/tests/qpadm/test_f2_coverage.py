"""Populations a request names are checked against the f2 cache before R starts."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.qpadm import (
    F4Spec,
    QpAdmMissingPopulations,
    QpAdmRotateSpec,
    QpAdmRunError,
    QpAdmSpec,
    check_f2_coverage,
    f2_populations,
    run_qpadm,
)


def _cache(root: Path, pops: list[str]) -> Path:
    root.mkdir()
    (root / "block_lengths_f2.rds").write_bytes(b"")
    (root / "cache_metadata.json").write_text("{}")
    (root / ".f2_cache_id").write_text("x")
    for p in pops:
        (root / p).mkdir()
    return root


def test_f2_populations_lists_population_directories_only(tmp_path: Path) -> None:
    cache = _cache(tmp_path / "f2", ["A", "B"])
    (cache / ".hidden").mkdir()
    assert f2_populations(cache) == frozenset({"A", "B"})


def test_a_directory_that_is_not_an_f2_cache_is_not_listed(tmp_path: Path) -> None:
    (tmp_path / "A").mkdir()
    assert f2_populations(tmp_path) is None
    assert f2_populations(tmp_path / "absent") is None
    assert f2_populations(None) is None


def test_missing_populations_are_named_in_request_order(tmp_path: Path) -> None:
    cache = _cache(tmp_path / "f2", ["T", "S1", "R1", "R2"])
    spec = QpAdmSpec(target="T", left=["S1", "S2"], right=["R1", "R2", "R3"], f2_dir=str(cache))
    with pytest.raises(QpAdmMissingPopulations) as info:
        check_f2_coverage(spec)
    assert info.value.missing == ["S2", "R3"]
    assert "(4 populations): S2, R3" in str(info.value)
    # A run error, so the job handler reports it as a permanent, readable failure.
    assert isinstance(info.value, QpAdmRunError)


def test_rotate_and_f4_specs_are_checked_too(tmp_path: Path) -> None:
    cache = _cache(tmp_path / "f2", ["T", "A", "B", "C"])
    rotate = QpAdmRotateSpec(target="T", leftright=["A", "B", "X"], f2_dir=str(cache))
    with pytest.raises(QpAdmMissingPopulations, match="X"):
        check_f2_coverage(rotate)
    f4 = F4Spec(pop1=["T"], pop2=["A"], pop3=["B"], pop4=["Y"], f2_dir=str(cache))
    with pytest.raises(QpAdmMissingPopulations, match="Y"):
        check_f2_coverage(f4)


def test_a_covered_request_passes(tmp_path: Path) -> None:
    cache = _cache(tmp_path / "f2", ["T", "S", "R1", "R2"])
    check_f2_coverage(QpAdmSpec(target="T", left=["S"], right=["R1", "R2"], f2_dir=str(cache)))


def test_run_qpadm_stops_before_r(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _cache(tmp_path / "f2", ["T", "R1", "R2"])

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("R must not start")

    monkeypatch.setattr("strata.qpadm.runner._invoke", boom)
    with pytest.raises(QpAdmMissingPopulations):
        run_qpadm(QpAdmSpec(target="T", left=["S"], right=["R1", "R2"], f2_dir=str(cache)))
