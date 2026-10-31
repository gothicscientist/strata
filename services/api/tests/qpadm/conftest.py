"""Fixtures for the ADMIXTOOLS 2 bridge tests.

Tests split into two groups:

* no marker — spec validation, feasibility interpretation and the error paths
  of the subprocess bridge. These run anywhere.
* `@pytest.mark.r` — real ADMIXTOOLS 2 computations. These need R plus the
  `admixtools` package and are skipped otherwise, so the suite stays green on
  a machine without the R environment.

The `r`-marked tests run against ADMIXTOOLS 2's own bundled f2 blocks
(`admixtools::example_f2_blocks`), exported to an f2 directory once per
session. Those are seven real populations (Neanderthal, Denisovan, Mbuti,
Chimp and three ancient modern humans), not simulated data, so the statistics
computed from them are genuine — but they are the package's demo populations
and have nothing to do with South Asia.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from example_data import requires_r  # noqa: F401  (re-exported for tests)

from strata.qpadm import qpadm_available, r_script_dir, rscript_path


@pytest.fixture(scope="session")
def example_f2_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Export `admixtools::example_f2_blocks` to an on-disk f2 cache.

    Built once per session because the export is the slow part; every
    `r`-marked test then reads the same cache, which is also what makes their
    numbers comparable to each other.
    """
    if not qpadm_available():
        pytest.skip("ADMIXTOOLS 2 unavailable")
    out = tmp_path_factory.mktemp("example_f2") / "f2"
    script = r_script_dir() / "export_example_f2.R"
    if not script.is_file():
        pytest.skip(f"{script} is missing")
    exe = rscript_path()
    assert exe is not None
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [exe, "--vanilla", str(script), str(out)],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
        env={**os.environ, "OMP_NUM_THREADS": "1"},
    )
    if proc.returncode != 0 or not out.is_dir():
        pytest.skip(f"could not export example f2 blocks: {proc.stderr[-2000:]}")
    return out


@pytest.fixture
def isolated_r_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the bridge at a directory with no R, to exercise the error paths."""
    monkeypatch.setenv("STRATA_RSCRIPT", "/nonexistent/Rscript")


@pytest.fixture(scope="session")
def has_rscript() -> bool:
    return rscript_path() is not None or shutil.which("Rscript") is not None
