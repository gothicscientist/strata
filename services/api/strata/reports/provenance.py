"""Provenance capture: code version, software versions, reference data version."""

from __future__ import annotations

import os
import platform
import subprocess
from functools import lru_cache
from importlib import metadata
from typing import Any

from strata import __version__
from strata.config import REPO_ROOT

TRACKED_PACKAGES = ("numpy", "scipy", "scikit-learn", "pandas", "pydantic", "fastapi",
                    "sqlalchemy", "cryptography")


@lru_cache(maxsize=1)
def code_version() -> dict[str, Any]:
    sha = os.environ.get("STRATA_GIT_SHA")
    dirty = None
    if not sha and (REPO_ROOT / ".git").exists():
        try:
            sha = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                                 capture_output=True, text=True, timeout=5,
                                 check=True).stdout.strip()
            dirty = bool(subprocess.run(
                ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--untracked-files=no"],
                capture_output=True, text=True, timeout=5).stdout.strip())
        except (OSError, subprocess.SubprocessError):
            sha = None
    return {"strata": __version__, "git_sha": sha, "git_dirty": dirty}


@lru_cache(maxsize=1)
def software_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {"python": platform.python_version()}
    for pkg in TRACKED_PACKAGES:
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = None
    return out


def base_provenance(seed: int | None, reference_version: str | None) -> dict[str, Any]:
    return {
        "code": code_version(),
        "software": software_versions(),
        "reference_version": reference_version,
        "seed": seed,
        "platform": platform.platform(terse=True),
    }
