from __future__ import annotations

import numpy as np

from strata.io import harmonize, parse_raw_dna
from strata.io.types import SnpPanel


def _raw(rows: list[tuple[str, str, int, str]], build: str = "37") -> object:
    text = f"# 23andMe SYNTHETIC\n# We are using reference human assembly build {build}\n"
    text += "".join(f"{r}\t{c}\t{p}\t{g}\n" for r, c, p, g in rows)
    return parse_raw_dna(text.encode(), "x.txt")


def _panel(rows: list[tuple[str, str, int, str, str]], build="GRCh37") -> SnpPanel:
    a = np.array(rows, dtype=object)
    return SnpPanel(
        name="test",
        build=build,
        rsid=a[:, 0],
        chrom=a[:, 1],
        pos=a[:, 2].astype(np.int64),
        ref=a[:, 3],
        alt=a[:, 4],
    )


PANEL = _panel(
    [
        ("rs1", "1", 100, "A", "G"),  # direct het
        ("rs2", "1", 200, "C", "T"),  # strand flipped hom (raw GG -> CC)
        ("rs3", "1", 300, "A", "T"),  # ambiguous -> dropped
        ("rs4", "1", 400, "A", "C"),  # mismatch (raw AG: neither strand fits)
        ("rs5", "1", 500, "G", "A"),  # no-call
        ("rs6", "2", 600, "C", "A"),  # matched by position (raw has internal id)
        ("rs7", "2", 700, "T", "C"),  # absent from raw
        ("rs8", "2", 800, "G", "T"),  # flip het: raw CA -> GT
    ]
)
RAW = [
    ("rs1", "1", 100, "AG"),
    ("rs2", "1", 200, "GG"),
    ("rs3", "1", 300, "AT"),
    ("rs4", "1", 400, "AG"),
    ("rs5", "1", 500, "--"),
    ("i123", "2", 600, "AA"),
    ("rs8", "2", 800, "CA"),
]


def test_harmonize_cases():
    h = harmonize(_raw(RAW), PANEL)
    d = h.dosage
    assert d[0] == 1  # one copy of ref A
    assert d[1] == 2  # GG on minus strand = CC = 2 copies of ref C
    assert np.isnan(d[2]) and np.isnan(d[3]) and np.isnan(d[4]) and np.isnan(d[6])
    assert d[5] == 0  # AA, ref C
    assert d[7] == 1
    o = h.overlap
    assert (o.matched_by_rsid, o.matched_by_position) == (6, 1)
    assert o.n_strand_flipped == 2 and o.n_ambiguous_dropped == 1
    assert o.n_allele_mismatch == 1 and o.mismatch_examples == ["rs4"]
    assert o.n_nocall == 1 and o.n_usable == 4 and o.overlap_fraction == 0.5
    assert h.counted_allele == "ref" and "dosage" not in h.model_dump()


def test_counted_alt():
    h = harmonize(_raw(RAW), PANEL, counted="alt")
    assert h.dosage[0] == 1 and h.dosage[1] == 0 and h.dosage[5] == 2


def test_no_position_fallback_across_builds():
    h = harmonize(_raw(RAW, build="36"), PANEL)
    assert h.overlap.matched_by_position == 0 and np.isnan(h.dosage[5])
    assert any(w.code == "no_position_fallback" for w in h.warnings)


def test_position_fallback_ignores_duplicate_positions():
    raw = _raw([("iA", "2", 600, "AA"), ("iB", "2", 600, "CC")])
    h = harmonize(raw, PANEL)
    assert h.overlap.matched_by_position == 0
