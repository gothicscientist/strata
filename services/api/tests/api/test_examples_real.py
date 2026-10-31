"""The committed data/examples (real ADMIXTOOLS 2 outputs) are served intact."""

from __future__ import annotations

import pytest

from strata.config import REPO_ROOT

EXAMPLES = REPO_ROOT / "data" / "examples"


@pytest.fixture
def real_examples_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from api.support import env_for, reset_platform_caches

    if not any(EXAMPLES.glob("*/example.json")):
        pytest.skip("no committed examples")
    for k, v in env_for(tmp_path, None, STRATA_EXAMPLES_DIR=str(EXAMPLES)).items():
        monkeypatch.setenv(k, v)
    reset_platform_caches()
    from strata.api.main import create_app

    with TestClient(create_app()) as c:
        yield c
    reset_platform_caches()


def test_real_examples_listed_with_caveats(real_examples_client):
    lst = real_examples_client.get("/api/v1/examples").json()
    assert lst and all(e["result_kind"] == "formal" for e in lst)
    for e in lst:
        assert e["caveats"], e["slug"]  # scope caveats are never dropped
        d = real_examples_client.get(f"/api/v1/examples/{e['slug']}").json()
        assert d["result"]["kind"] == "formal" and d["caveats"] == e["caveats"]
        assert d["provenance"]
