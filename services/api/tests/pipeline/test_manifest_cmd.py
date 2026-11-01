"""The manifest stage's two guards.

A manifest is the only record of where the derived data came from. Nothing
downstream can reconstruct it, and `verify` does not judge it — verify re-hashes
the artefacts a manifest names, so a manifest that has lost its sources still
verifies clean. That makes a silent downgrade the dangerous failure here, and
these tests pin the two cases that produce one.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pytest
from pipeline.__main__ import cmd_manifest


def _derived(root: Path, counts: dict[str, int] | None = None) -> Path:
    derived = root / "data" / "derived"
    derived.mkdir(parents=True)
    pd.DataFrame({"id": [1, 2, 3], "group_id": ["A", "B", "C"]}).to_parquet(
        derived / "populations.parquet", index=False
    )
    pd.DataFrame({"id": list(range(7))}).to_parquet(derived / "samples.parquet", index=False)
    (derived / "MANIFEST.json").write_text(
        json.dumps(
            {
                "version": "strata-ref-v1",
                "built_at": "2026-01-01T00:00:00Z",
                "sources": [{"name": "AADR v66.p1 HO: x.geno", "sha256": "abc"}],
                "counts": counts if counts is not None else {"populations": 1, "samples": 1},
                "exclusions": {"1240K": {"total_excluded": 5}},
                "artefacts": {},
            }
        ),
        encoding="utf-8",
    )
    return derived


def _args(root: Path, **kw) -> argparse.Namespace:
    return argparse.Namespace(
        root=root, aadr_version="v66.p1", reference_version="strata-ref-v1", **kw
    )


def test_a_run_without_pipeline_state_refuses_to_overwrite_a_fuller_manifest(
    tmp_path, capsys
) -> None:
    derived = _derived(tmp_path)
    before = (derived / "MANIFEST.json").read_text(encoding="utf-8")

    assert cmd_manifest(_args(tmp_path, refresh=False)) == 2

    assert (derived / "MANIFEST.json").read_text(encoding="utf-8") == before
    err = capsys.readouterr().err
    assert "--refresh" in err  # the message has to name the way forward


def test_refresh_keeps_the_provenance_and_updates_the_counts(tmp_path) -> None:
    derived = _derived(tmp_path)

    assert cmd_manifest(_args(tmp_path, refresh=True)) == 0

    man = json.loads((derived / "MANIFEST.json").read_text(encoding="utf-8"))
    assert man["sources"] == [{"name": "AADR v66.p1 HO: x.geno", "sha256": "abc"}]
    assert man["exclusions"] == {"1240K": {"total_excluded": 5}}
    # Counts come from the tables, not from the record they are replacing.
    assert man["counts"]["populations"] == 3
    assert man["counts"]["samples"] == 7
    assert man["built_at"] != "2026-01-01T00:00:00Z"
    assert set(man["artefacts"]) == {"populations.parquet", "samples.parquet"}


def test_refresh_without_a_manifest_is_an_error_not_an_empty_one(tmp_path, capsys) -> None:
    derived = tmp_path / "data" / "derived"
    derived.mkdir(parents=True)
    pd.DataFrame({"id": [1]}).to_parquet(derived / "populations.parquet", index=False)

    assert cmd_manifest(_args(tmp_path, refresh=True)) == 2
    assert "there is none" in capsys.readouterr().err
    assert not (derived / "MANIFEST.json").exists()


def test_nothing_to_describe_is_reported_before_anything_is_written(tmp_path, capsys) -> None:
    (tmp_path / "data" / "derived").mkdir(parents=True)

    assert cmd_manifest(_args(tmp_path, refresh=False)) == 2
    assert "run `curate` first" in capsys.readouterr().err


@pytest.mark.parametrize("refresh", [True, False])
def test_a_manifest_is_never_written_on_a_refusal(tmp_path, refresh) -> None:
    """Whichever guard fires, the file on disk is the one that was there."""
    derived = _derived(tmp_path, counts={})
    before = (derived / "MANIFEST.json").read_text(encoding="utf-8")
    code = cmd_manifest(_args(tmp_path, refresh=refresh))
    if code != 0:
        assert (derived / "MANIFEST.json").read_text(encoding="utf-8") == before


def test_the_onekg_stage_records_its_source_in_the_manifest(tmp_path) -> None:
    """A reader who sees `Gujarati_1000G` must find its origin in the record."""
    from pipeline import onekg
    from pipeline.__main__ import _record_onekg_source

    derived = _derived(tmp_path)
    note = _record_onekg_source(derived, onekg, ["1", "22"])

    man = json.loads((derived / "MANIFEST.json").read_text(encoding="utf-8"))
    names = [s["name"] for s in man["sources"]]
    assert "AADR v66.p1 HO: x.geno" in names  # the first source is not displaced
    assert any(n.startswith("1000 Genomes phase 3") for n in names)
    assert man["citations"]["1000_genomes"] == [onekg.CITATION]
    assert "1000 Genomes" in note


def test_recording_the_source_twice_does_not_stack_up_entries(tmp_path) -> None:
    from pipeline import onekg
    from pipeline.__main__ import _record_onekg_source

    derived = _derived(tmp_path)
    _record_onekg_source(derived, onekg, ["1"])
    _record_onekg_source(derived, onekg, list(onekg.AUTOSOMES))

    man = json.loads((derived / "MANIFEST.json").read_text(encoding="utf-8"))
    onekg_entries = [s for s in man["sources"] if s["name"].startswith("1000 Genomes")]
    assert len(onekg_entries) == 1
    # The surviving entry is the later one, describing the whole run.
    assert "22 autosomes" in onekg_entries[0]["note"]


def test_recording_the_source_without_a_manifest_says_so_rather_than_failing(tmp_path) -> None:
    from pipeline import onekg
    from pipeline.__main__ import _record_onekg_source

    derived = tmp_path / "data" / "derived"
    derived.mkdir(parents=True)
    note = _record_onekg_source(derived, onekg, ["1"])

    assert "no manifest" in note
    assert not (derived / "MANIFEST.json").exists()
