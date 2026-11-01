"""Global25-style coordinate parsing: ``Name,PC1,...,PC25`` rows (comma or tab separated)."""

from __future__ import annotations

import csv
import io
import math

import numpy as np

from strata.io.errors import InputFormatError
from strata.io.types import G25Table, ParseWarning

G25_DIMS = 25
_MAX_ABS_PLAUSIBLE = 1.0


def _is_float(s: str) -> bool:
    try:
        float(s)
    except ValueError:
        return False
    return True


def _detect_delimiter(line: str) -> str:
    if "\t" in line:
        return "\t"
    if "," in line:
        return ","
    if ";" in line:
        return ";"
    return ","


def infer_scaling(matrix: np.ndarray) -> bool | None:
    """Heuristic: scaled G25 coordinates have strongly decreasing magnitude across PCs
    (PC1 >> PC25), unscaled coordinates have roughly equal magnitude per PC."""
    if matrix.size == 0 or matrix.shape[1] < 10:
        return None
    head = float(np.mean(np.abs(matrix[:, :3])))
    tail = float(np.mean(np.abs(matrix[:, -10:])))
    if tail == 0:
        return None
    ratio = head / tail
    if ratio > 3.0:
        return True
    if ratio < 1.5:
        return False
    return None


def parse_g25(text: str, *, n_dims: int | None = G25_DIMS) -> G25Table:
    """Parse G25-style coordinates.

    ``n_dims=None`` infers the dimensionality from the first data row (used for other spaces).
    Rows with the wrong number of columns or non-finite values are skipped with a warning.
    Duplicate names with identical values are dropped; with different values they are
    renamed ``name#2`` etc.
    """
    text = text.lstrip("﻿")
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    if not lines:
        raise InputFormatError("No coordinate rows found.")
    delim = _detect_delimiter(lines[0])
    rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))

    warnings: list[ParseWarning] = []
    first = [f.strip() for f in rows[0]]
    if len(first) > 1 and not all(_is_float(f) for f in first[1:] if f):
        rows = rows[1:]  # header row
    if not rows:
        raise InputFormatError("Only a header row was found.")

    names: list[str] = []
    values: list[list[float]] = []
    bad_width = bad_value = 0
    seen: dict[str, int] = {}
    n_dup_dropped = n_dup_renamed = 0
    for raw in rows:
        fields = [f.strip() for f in raw]
        while fields and fields[-1] == "":
            fields.pop()
        if len(fields) < 2:
            bad_width += 1
            continue
        name, nums = fields[0].strip('"'), fields[1:]
        if n_dims is None:
            n_dims = len(nums)
        if len(nums) != n_dims:
            bad_width += 1
            continue
        try:
            vec = [float(x) for x in nums]
        except ValueError:
            bad_value += 1
            continue
        if not all(math.isfinite(v) for v in vec):
            bad_value += 1
            continue
        if not name:
            bad_value += 1
            continue
        if name in seen:
            if values[seen[name]] == vec:
                n_dup_dropped += 1
                continue
            k = 2
            while f"{name}#{k}" in seen:
                k += 1
            name = f"{name}#{k}"
            n_dup_renamed += 1
        seen[name] = len(names)
        names.append(name)
        values.append(vec)

    if bad_width:
        warnings.append(
            ParseWarning(
                code="wrong_width",
                message=f"Skipped rows without exactly {n_dims} numeric columns.",
                count=bad_width,
            )
        )
    if bad_value:
        warnings.append(
            ParseWarning(
                code="invalid_value",
                message="Skipped rows with empty names or non-numeric/non-finite values.",
                count=bad_value,
            )
        )
    if n_dup_dropped:
        warnings.append(
            ParseWarning(
                code="duplicate_identical",
                message="Dropped exact duplicate rows.",
                count=n_dup_dropped,
            )
        )
    if n_dup_renamed:
        warnings.append(
            ParseWarning(
                code="duplicate_renamed",
                message="Duplicate names with different coordinates were renamed 'name#k'.",
                count=n_dup_renamed,
            )
        )
    if not names:
        raise InputFormatError(
            f"No valid rows: expected a name followed by {n_dims} numeric columns."
        )
    matrix = np.asarray(values, dtype=np.float64)
    n_implausible = int(np.sum(np.any(np.abs(matrix) > _MAX_ABS_PLAUSIBLE, axis=1)))
    if n_implausible:
        warnings.append(
            ParseWarning(
                code="implausible_range",
                message=f"Rows with |value| > {_MAX_ABS_PLAUSIBLE}; G25 coordinates are "
                "normally well inside [-0.5, 0.5]. Check the input is G25 coordinates.",
                count=n_implausible,
            )
        )
    scaled = infer_scaling(matrix) if n_dims == G25_DIMS else None
    if scaled is False:
        warnings.append(
            ParseWarning(
                code="unscaled",
                message="Coordinates look unscaled (similar magnitude on all PCs). Strata's "
                "G25 reference is scaled; mixing scaled and unscaled coordinates is invalid.",
            )
        )
    return G25Table(
        names=names, matrix=matrix, n_dims=int(n_dims), scaled=scaled, warnings=warnings
    )
