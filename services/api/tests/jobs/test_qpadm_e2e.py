"""Formal qpAdm through the API job path, on ADMIXTOOLS 2's bundled example f2 blocks (real
data: archaic hominins). Requires R + ADMIXTOOLS 2."""

from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.r


@pytest.fixture(scope="module")
def example_f2(tmp_path_factory):
    from strata.qpadm import qpadm_available, r_script_dir, rscript_path

    if not qpadm_available():
        pytest.skip("R + ADMIXTOOLS 2 not available")
    dest = tmp_path_factory.mktemp("f2")
    script = r_script_dir() / "export_example_f2.R"
    proc = subprocess.run(
        [str(rscript_path()), "--vanilla", str(script), str(dest)],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return dest


def test_qpadm_job_end_to_end(monkeypatch, tmp_path, example_f2):
    from api.support import env_for, reset_platform_caches
    from fastapi.testclient import TestClient

    for k, v in env_for(tmp_path, None, STRATA_F2_DIR=str(example_f2)).items():
        monkeypatch.setenv(k, v)
    reset_platform_caches()
    from strata.api.main import create_app

    right = ["Chimp.REF", "Mbuti.DG", "Russia_Ust_Ishim.DG", "Switzerland_Bichon.SG"]
    with TestClient(create_app()) as c:
        h = {"Authorization": f"Bearer {c.post('/api/v1/auth/guest').json()['token']}"}
        r = c.post(
            "/api/v1/analyses",
            headers=h,
            json={
                "kind": "qpadm",
                "target": "Denisova.DG",
                "params": {"left": ["Altai_Neanderthal.DG", "Vindija.DG"], "right": right},
            },
        )
        assert r.status_code == 201, r.text
        a = r.json()["analysis"]
        assert a["status"] == "succeeded", a
        res = a["result"]
        assert res["kind"] == "formal" and res["dof"] == 2
        assert 0 <= res["p_value"] <= 1 and len(res["weights"]) == 2
        # Denisova is not a mixture of two Neanderthals: weights fall far outside [0, 1].
        assert res["feasible"] is False and res["verdict"] == "infeasible"
        assert a["provenance"]["r"] and a["provenance"]["inputs"]["f2_dir"] == str(example_f2)
        html = c.get(f"/api/v1/analyses/{a['id']}/report", headers=h)
        assert "Formal test" in html.text and "infeasible" in html.text
        # Client-chosen f2 paths are refused.
        r = c.post(
            "/api/v1/analyses",
            headers=h,
            json={
                "kind": "qpadm",
                "target": "Denisova.DG",
                "params": {"left": ["Vindija.DG"], "right": right, "f2_dir": "/etc"},
            },
        )
        assert r.json()["analysis"]["status"] == "failed"
    reset_platform_caches()
