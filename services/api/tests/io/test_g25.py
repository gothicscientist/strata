from __future__ import annotations

import numpy as np
import pytest

from strata.io import InputFormatError, parse_g25

SCALED = [0.1, -0.05, 0.04, 0.03, -0.02] + [0.004] * 20  # synthetic, G25-like magnitudes


def row(name: str, vals=SCALED, sep=","):
    return name + sep + sep.join(f"{v:.6f}" for v in vals)


def test_header_and_colon_names():
    text = "Pop,PC1," + ",".join(f"PC{i}" for i in range(2, 26)) + "\n"
    text += row("Turkey_N:I0736") + "\n" + row("Iran_GanjDareh_N:I1945", [v * 1.1 for v in SCALED])
    t = parse_g25(text)
    assert t.names == ["Turkey_N:I0736", "Iran_GanjDareh_N:I1945"]
    assert t.matrix.shape == (2, 25) and t.matrix.dtype == np.float64
    assert t.scaled is True and not t.warnings


def test_tab_no_header_and_comments():
    t = parse_g25("# comment\n" + row("a", sep="\t") + "\n\n" + row("b", sep="\t") + "\n")
    assert t.names == ["a", "b"]


def test_duplicates_and_bad_rows():
    text = "\n".join(
        [
            row("a"),
            row("a"),
            row("a", [v + 0.01 for v in SCALED]),
            "b,1,2,3",
            "c,x," + row("", SCALED[1:])[1:],
            row("d", [float("nan")] + SCALED[1:]),
        ]
    )
    t = parse_g25(text)
    assert t.names == ["a", "a#2"]
    codes = {w.code: w.count for w in t.warnings}
    assert codes == {
        "wrong_width": 1,
        "invalid_value": 2,
        "duplicate_identical": 1,
        "duplicate_renamed": 1,
    }


def test_unscaled_and_implausible():
    vals = [0.02, -0.02] * 12 + [0.02]
    t = parse_g25(row("u", vals))
    assert t.scaled is False and any(w.code == "unscaled" for w in t.warnings)
    t2 = parse_g25(row("big", [5.0] + SCALED[1:]))
    assert any(w.code == "implausible_range" for w in t2.warnings)


def test_other_dimensionality_and_errors():
    t = parse_g25("x,1,2,3\ny,4,5,6", n_dims=None)
    assert t.n_dims == 3 and t.scaled is None
    with pytest.raises(InputFormatError):
        parse_g25("")
    with pytest.raises(InputFormatError):
        parse_g25("a,1,2,3")
