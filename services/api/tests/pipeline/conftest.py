"""Make `data/pipeline` importable as `pipeline` for these tests.

The pipeline is not a published package: it lives beside the data it builds and
is invoked as `python -m pipeline` from `data/pipeline`. Tests add that
directory to `sys.path` rather than installing it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
PIPELINE_DIR = REPO_ROOT / "data" / "pipeline"
FIXTURES = PIPELINE_DIR / "tests" / "fixtures"

if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def mini_anno(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "mini.anno"
    if not path.is_file():
        pytest.skip(f"fixture missing: {path}")
    return path
