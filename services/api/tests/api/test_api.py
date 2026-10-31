"""End-to-end API tests on SQLite with inline jobs. Reference data is SYNTHETIC."""

from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pytest

from api.conftest import guest
from api.support import POPS, SYNTHETIC_VERSION, g25_centers, make_23andme

V = "/api/v1"


def _g25_line(name: str, vec: np.ndarray) -> str:
    return name + "," + ",".join(f"{x:.6f}" for x in vec)


# ------------------------------------------------------------------ health / auth


def test_health_reports_missing_capabilities_honestly(client):
    r = client.get(f"{V}/health")
    assert r.status_code == 200
    caps = r.json()["capabilities"]
    assert caps["reference_loaded"] is False
    assert caps["reference_version"] is None
    assert caps["llm_configured"] is False
    assert caps["job_mode"] == "inline"
    assert "admixture_fit" in caps["job_kinds"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_health_with_reference(ref_client):
    caps = ref_client.get(f"{V}/health").json()["capabilities"]
    assert caps["reference_loaded"] is True
    assert caps["reference_version"] == SYNTHETIC_VERSION
    assert caps["snp_panel_loaded"] is True
    assert caps["pca_space"] == "strata-pca-v1"


def test_auth_required_and_bad_tokens(client):
    assert client.get(f"{V}/datasets").status_code == 401
    r = client.get(f"{V}/datasets", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert client.get(f"{V}/datasets", headers={"Authorization": "Basic x"}).status_code == 401
    h = guest(client)
    me = client.get(f"{V}/auth/me", headers=h).json()
    assert me["kind"] == "guest" and me["expires_at"]


def test_openapi_lists_every_route(client):
    spec = client.get(f"{V}/openapi.json").json()
    paths = spec["paths"]
    for p in [
        "/health",
        "/auth/guest",
        "/reference/populations",
        "/reference/populations/{population_id}",
        "/reference/spaces",
        "/reference/publications",
        "/datasets",
        "/datasets/{dataset_id}",
        "/analyses",
        "/analyses/{analysis_id}",
        "/analyses/{analysis_id}/report",
        "/jobs/{job_id}",
        "/examples",
        "/examples/{slug}",
        "/chat/sessions",
        "/chat/sessions/{session_id}/messages",
    ]:
        assert f"{V}{p}" in paths, p
    assert {t["name"] for t in spec["tags"]} >= {"datasets", "analyses", "chat"}


# ------------------------------------------------------------------ datasets


def test_g25_upload_qc_and_isolation(client):
    a, b = guest(client), guest(client)
    vec = np.linspace(0.1, 0.001, 25)
    r = client.post(
        f"{V}/datasets",
        headers=a,
        data={"kind": "g25", "g25_text": _g25_line("Me", vec), "name": "mine"},
    )
    assert r.status_code == 201, r.text
    ds = r.json()
    assert ds["kind"] == "g25" and ds["space"] == "g25" and ds["sample_names"] == ["Me"]
    assert ds["qc"]["n_samples"] == 1 and len(ds["input_sha256"]) == 64
    did = ds["id"]
    # Owner sees it; another guest gets 404 (not 403: no existence oracle).
    assert client.get(f"{V}/datasets/{did}", headers=a).status_code == 200
    assert client.get(f"{V}/datasets/{did}", headers=b).status_code == 404
    assert client.get(f"{V}/datasets", headers=b).json() == []
    assert client.delete(f"{V}/datasets/{did}", headers=b).status_code == 404
    r = client.post(
        f"{V}/analyses", headers=b, json={"kind": "pca_project", "dataset_id": did, "params": {}}
    )
    assert r.status_code == 404


def test_raw_upload_without_panel_stores_calls(client):
    h = guest(client)
    r = client.post(
        f"{V}/datasets",
        headers=h,
        files={"file": ("genome_Jane_Doe_v5.txt", make_23andme(), "text/plain")},
    )
    assert r.status_code == 201, r.text
    ds = r.json()
    assert ds["kind"] == "raw_dna"
    assert ds["qc"]["vendor"] == "23andme" and ds["qc"]["build"] == "GRCh37"
    assert ds["qc"]["n_indels_dropped"] >= 1 and ds["qc"]["n_no_calls"] > 0
    assert ds["summary"]["harmonized"] is False
    assert any("panel not installed" in w for w in ds["qc"]["warnings"])


def test_raw_upload_zip_and_rejections(client):
    h = guest(client)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("genome.txt", make_23andme())
    r = client.post(
        f"{V}/datasets",
        headers=h,
        files={"file": ("../../etc/genome.zip", buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "raw_dna"
    r = client.post(
        f"{V}/datasets",
        headers=h,
        files={"file": ("x.exe", b"MZ\x00\x00", "application/octet-stream")},
    )
    assert r.status_code == 415
    r = client.post(
        f"{V}/datasets", headers=h, files={"file": ("bin.txt", b"\x00\x01\x02" * 100, "text/plain")}
    )
    assert r.status_code == 415
    r = client.post(f"{V}/datasets", headers=h, data={"kind": "g25", "g25_text": "a,b,c"})
    assert r.status_code == 422


def test_upload_size_limit(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from api.support import env_for, reset_platform_caches

    for k, v in env_for(tmp_path, None, STRATA_MAX_UPLOAD_MB="0.002").items():
        monkeypatch.setenv(k, v)
    reset_platform_caches()
    from strata.api.main import create_app

    with TestClient(create_app()) as c:
        h = guest(c)
        r = c.post(
            f"{V}/datasets", headers=h, files={"file": ("g.txt", make_23andme(), "text/plain")}
        )
        assert r.status_code == 413
    reset_platform_caches()


def test_delete_shreds_key(client):
    from strata.db.models import Dataset, DatasetKey
    from strata.db.session import get_sessionmaker

    h = guest(client)
    did = client.post(
        f"{V}/datasets",
        headers=h,
        data={"kind": "g25", "g25_text": _g25_line("Me", np.linspace(0.1, 0.001, 25))},
    ).json()["id"]
    import uuid

    with get_sessionmaker()() as s:
        ds = s.get(Dataset, uuid.UUID(did))
        assert ds.ciphertext and b"Me" not in ds.ciphertext  # encrypted at rest
        assert s.get(DatasetKey, uuid.UUID(did)) is not None
    assert client.delete(f"{V}/datasets/{did}", headers=h).status_code == 204
    with get_sessionmaker()() as s:
        assert s.get(DatasetKey, uuid.UUID(did)) is None
        assert s.get(Dataset, uuid.UUID(did)) is None
    assert client.get(f"{V}/datasets/{did}", headers=h).status_code == 404


# ------------------------------------------------------------------ reference


def test_reference_unavailable_is_503(client):
    r = client.get(f"{V}/reference/populations")
    assert r.status_code == 503 and r.json()["code"] == "reference_unavailable"


def test_reference_endpoints(ref_client):
    r = ref_client.get(f"{V}/reference/populations", params={"q": "popb"})
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["id"] == "PopB"
    assert body["facets"]["source_dataset"] == ["SYNTHETIC"]
    r = ref_client.get(
        f"{V}/reference/populations", params={"min_bp": 5800, "max_bp": 6200, "page_size": 1}
    )
    assert r.json()["total"] == 1
    d = ref_client.get(f"{V}/reference/populations/PopA").json()
    assert len(d["samples"]) == 8 and d["publications"][0]["id"] == "synth2026"
    assert ref_client.get(f"{V}/reference/populations/Nope").status_code == 404
    spaces = ref_client.get(f"{V}/reference/spaces").json()
    pca = next(s for s in spaces if s["id"] == "strata-pca-v1")
    assert len(pca["populations"]) == 3 and len(pca["populations"][0]["coords"]) == 4
    assert pca["explained_variance"]
    assert ref_client.get(f"{V}/reference/publications").json()[0]["year"] == 2026


# ------------------------------------------------------------------ analyses end to end


def test_raw_dna_harmonise_project_nearest_report(ref_client):
    h = guest(ref_client)
    ds = ref_client.post(
        f"{V}/datasets",
        headers=h,
        files={"file": ("genome.txt", make_23andme("PopB"), "text/plain")},
    ).json()
    assert ds["summary"]["harmonized"] is True
    assert ds["qc"]["panel_size"] == 400 and ds["qc"]["panel_overlap"] > 0.9

    r = ref_client.post(
        f"{V}/analyses",
        headers=h,
        json={"kind": "pca_project", "dataset_id": ds["id"], "params": {}},
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["job"]["status"] == "succeeded", out
    res = out["analysis"]["result"]
    assert res["kind"] == "exploratory" and res["space"] == "strata-pca-v1"
    assert len(res["targets"][0]["coords"]) == 4 and res["n_snps_used"] > 300

    r = ref_client.post(
        f"{V}/analyses",
        headers=h,
        json={"kind": "nearest", "dataset_id": ds["id"], "params": {"k": 3}},
    )
    near = r.json()["analysis"]
    assert near["status"] == "succeeded", near
    assert near["result"]["hits"][0]["population_id"] == "PopB"
    prov = near["provenance"]
    assert prov["reference_version"] == SYNTHETIC_VERSION
    assert prov["inputs"]["dataset"]["input_sha256"] == ds["input_sha256"]

    job = ref_client.get(f"{V}/jobs/{r.json()['job']['id']}", headers=h).json()
    assert job["status"] == "succeeded" and job["analysis_id"] == near["id"]

    rep = ref_client.get(f"{V}/analyses/{near['id']}/report", headers=h, params={"format": "json"})
    assert rep.status_code == 200 and "attachment" in rep.headers["content-disposition"]
    bundle = rep.json()
    from strata.reports import verify_bundle

    assert verify_bundle(bundle)
    assert bundle["classification"] == "exploratory"
    assert bundle["inputs"][0]["input_sha256"] == ds["input_sha256"]
    html = ref_client.get(f"{V}/analyses/{near['id']}/report", headers=h)
    assert html.headers["content-type"].startswith("text/html")
    assert "Exploratory analysis" in html.text and "bundle SHA-256" in html.text
    assert "frame-ancestors 'none'" in html.headers["content-security-policy"]
    # Report HTML never carries genotype calls.
    assert "rs900001\t" not in html.text


def test_g25_admixture_fit_and_rotation(ref_client, synthetic_derived):
    h = guest(ref_client)
    c = g25_centers(synthetic_derived)
    target = 0.6 * c["PopA"] + 0.4 * c["PopB"]
    ds = ref_client.post(
        f"{V}/datasets", headers=h, data={"kind": "g25", "g25_text": _g25_line("Mix", target)}
    ).json()
    r = ref_client.post(
        f"{V}/analyses",
        headers=h,
        json={
            "kind": "admixture_fit",
            "dataset_id": ds["id"],
            "title": "two-way",
            "params": {"sources": list(POPS), "bootstrap": 100, "seed": 1},
        },
    )
    a = r.json()["analysis"]
    assert a["status"] == "succeeded", a
    res = a["result"]
    w = {x["source"]: x for x in res["weights"]}
    assert abs(w["PopA"]["weight"] - 0.6) < 0.05 and abs(w["PopB"]["weight"] - 0.4) < 0.05
    assert w["PopA"]["ci_low"] <= w["PopA"]["weight"] <= w["PopA"]["ci_high"]
    assert res["n_bootstrap"] == 100 and res["kind"] == "exploratory"
    assert res["sensitivity"]["leave_one_source_out"]
    assert a["provenance"]["seed"] == 1

    r = ref_client.post(
        f"{V}/analyses",
        headers=h,
        json={
            "kind": "admixture_rotate",
            "dataset_id": ds["id"],
            "params": {"candidates": list(POPS), "min_sources": 1, "max_sources": 2},
        },
    )
    rot = r.json()["analysis"]
    assert rot["status"] == "succeeded", rot
    assert set(rot["result"]["models"][0]["sources"]) == {"PopA", "PopB"}

    lst = ref_client.get(f"{V}/analyses", headers=h).json()
    assert {x["kind"] for x in lst} == {"admixture_fit", "admixture_rotate"}

    cmp = ref_client.post(
        f"{V}/analyses/../comparisons".replace("/analyses/..", ""),
        headers=h,
        json={"name": "fit vs rot", "analysis_ids": [a["id"], rot["id"]]},
    )
    assert cmp.status_code == 201 and len(cmp.json()["summary"]["models"]) == 2


def test_g25_source_sheet(ref_client, synthetic_derived):
    h = guest(ref_client)
    c = g25_centers(synthetic_derived)
    rng = np.random.default_rng(5)
    sheet = "\n".join(
        _g25_line(f"{p}:ind{i}", c[p] + rng.normal(0, 0.002, 25))
        for p in ("PopA", "PopC")
        for i in range(4)
    )
    src = ref_client.post(
        f"{V}/datasets", headers=h, data={"kind": "g25", "g25_text": sheet}
    ).json()
    tgt = ref_client.post(
        f"{V}/datasets",
        headers=h,
        data={"kind": "g25", "g25_text": _g25_line("T", 0.3 * c["PopA"] + 0.7 * c["PopC"])},
    ).json()
    r = ref_client.post(
        f"{V}/analyses",
        headers=h,
        json={
            "kind": "admixture_fit",
            "dataset_id": tgt["id"],
            "params": {"source_dataset_id": src["id"], "n_bootstrap": 50},
        },
    )
    a = r.json()["analysis"]
    assert a["status"] == "succeeded", a
    w = {x["source"]: x["weight"] for x in a["result"]["weights"]}
    assert abs(w["PopC"] - 0.7) < 0.05
    assert len(a["dataset_ids"]) == 2
    # Another user cannot use my sheet as a source.
    other = guest(ref_client)
    r = ref_client.post(
        f"{V}/analyses",
        headers=other,
        json={
            "kind": "admixture_fit",
            "target": "PopA",
            "params": {"source_dataset_id": src["id"]},
        },
    )
    assert r.status_code == 404


def test_failed_analysis_reports_error(ref_client):
    h = guest(ref_client)
    r = ref_client.post(
        f"{V}/analyses",
        headers=h,
        json={"kind": "admixture_fit", "target": "PopA", "params": {"sources": ["Nope"]}},
    )
    out = r.json()
    assert out["job"]["status"] == "failed" and out["job"]["attempts"] == 1
    assert out["analysis"]["status"] == "failed" and "Nope" in out["analysis"]["error"]
    rep = ref_client.get(f"{V}/analyses/{out['analysis']['id']}/report", headers=h)
    assert rep.status_code == 409


def test_qpadm_unavailable_inline(ref_client):
    h = guest(ref_client)
    from strata.api import science

    if science.qpadm_available():
        pytest.skip("ADMIXTOOLS 2 installed here")
    r = ref_client.post(
        f"{V}/analyses",
        headers=h,
        json={
            "kind": "qpadm",
            "target": "PopA",
            "params": {"left": ["PopB"], "right": ["PopC", "X", "Y"]},
        },
    )
    assert r.status_code == 503 and r.json()["code"] == "qpadm_unavailable"


# ------------------------------------------------------------------ examples / chat


def test_examples(client, tmp_path):
    from strata.config import get_settings

    root = get_settings().examples_dir
    (root / "demo-fit").mkdir(parents=True)
    (root / "demo-fit" / "example.json").write_text(
        json.dumps(
            {
                "title": "Demo",
                "summary": "s",
                "kind": "qpadm",
                "result_kind": "formal",
                "result": {"type": "qpadm", "kind": "formal"},
                "provenance": {"r": "4.5"},
            }
        )
    )
    (root / "broken").mkdir()
    lst = client.get(f"{V}/examples").json()
    assert [e["slug"] for e in lst] == ["demo-fit"] and "result" not in lst[0]
    d = client.get(f"{V}/examples/demo-fit").json()
    assert d["result"]["kind"] == "formal" and d["provenance"]["r"] == "4.5"
    assert client.get(f"{V}/examples/..%2Fetc").status_code == 404
    assert client.get(f"{V}/examples/missing").status_code == 404


def test_chat_sessions_and_llm_unavailable(client):
    h = guest(client)
    other = guest(client)
    s = client.post(f"{V}/chat/sessions", headers=h, json={"title": "t"})
    assert s.status_code == 201
    sid = s.json()["id"]
    assert client.get(f"{V}/chat/sessions/{sid}", headers=other).status_code == 404
    r = client.post(f"{V}/chat/sessions/{sid}/messages", headers=h, json={"content": "hi"})
    assert r.status_code == 503 and r.json()["code"] == "llm_unavailable"
    assert client.get(f"{V}/chat/sessions/{sid}", headers=h).json()["messages"] == []


def test_chat_stream_persists_audit(client, monkeypatch):
    """Drives the real SSE endpoint with a stand-in for strata.agent.stream_chat (TEST DOUBLE:
    a scripted event sequence, no LLM). Verifies streaming order and audit persistence."""
    import strata.agent as agent_mod
    from strata.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    seen = {}

    async def fake_stream(history, user_message, *, ctx, cancel=None, **_):
        seen["history"], seen["ctx"] = history, ctx
        datasets = ctx.list_datasets(ctx.user_id)
        yield {"type": "tool_call", "id": "t1", "name": "list_user_datasets", "arguments": {}}
        yield {
            "type": "tool_result",
            "id": "t1",
            "name": "list_user_datasets",
            "ok": True,
            "result": {"datasets": datasets},
        }
        yield {"type": "text_delta", "text": "You have "}
        yield {"type": "text_delta", "text": f"{len(datasets)} dataset(s)."}
        yield {
            "type": "done",
            "answer": f"You have {len(datasets)} dataset(s).",
            "grounding": {"ok": True, "ungrounded": []},
            "citations": [],
            "transcript": [{"step": 1}],
            "usage": {"input_tokens": 1},
        }

    monkeypatch.setattr(agent_mod, "stream_chat", fake_stream)
    h = guest(client)
    client.post(
        f"{V}/datasets",
        headers=h,
        data={"kind": "g25", "g25_text": _g25_line("Me", np.linspace(0.1, 0.001, 25))},
    )
    sid = client.post(f"{V}/chat/sessions", headers=h, json={}).json()["id"]
    with client.stream(
        "POST",
        f"{V}/chat/sessions/{sid}/messages",
        headers=h,
        json={"content": "how many datasets?"},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [ln[len("event: ") :] for ln in r.iter_lines() if ln.startswith("event: ")]
    assert events == ["tool_call", "tool_result", "text_delta", "text_delta", "saved", "done"]
    detail = client.get(f"{V}/chat/sessions/{sid}", headers=h).json()
    user, asst = detail["messages"]
    assert user["role"] == "user" and asst["content"] == "You have 1 dataset(s)."
    assert asst["tool_calls"][0]["name"] == "list_user_datasets"
    assert asst["tool_results"][0]["ok"] is True
    assert asst["grounding"]["ok"] is True
    # Tool context exposes metadata only, never payloads or genotypes.
    ds_meta = asst["tool_results"][0]["result"]["datasets"][0]
    assert "ciphertext" not in ds_meta and "matrix" not in json.dumps(ds_meta)
    assert detail["title"] == "how many datasets?"


def test_retention_purges_expired_guest(client):
    import uuid
    from datetime import timedelta

    from strata.db.models import Dataset, DatasetKey, User
    from strata.db.session import get_sessionmaker
    from strata.db.types import utcnow
    from strata.security.retention import purge_expired
    from strata.security.vault import vault_from_settings

    h = guest(client)
    did = client.post(
        f"{V}/datasets",
        headers=h,
        data={"kind": "g25", "g25_text": _g25_line("Me", np.linspace(0.1, 0.001, 25))},
    ).json()["id"]
    uid = client.get(f"{V}/auth/me", headers=h).json()["id"]
    with get_sessionmaker()() as s, s.begin():
        counts = purge_expired(s, vault_from_settings(), now=utcnow() + timedelta(hours=25))
    assert counts["datasets"] == 1 and counts["guests"] == 1
    with get_sessionmaker()() as s:
        assert s.get(User, uuid.UUID(uid)) is None
        assert s.get(DatasetKey, uuid.UUID(did)) is None and s.get(Dataset, uuid.UUID(did)) is None
    assert client.get(f"{V}/datasets", headers=h).status_code == 401


def test_rate_limit(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from api.support import env_for, reset_platform_caches

    for k, v in env_for(
        tmp_path, None, STRATA_RATE_LIMIT_PER_MINUTE="60", STRATA_RATE_LIMIT_BURST="3"
    ).items():
        monkeypatch.setenv(k, v)
    reset_platform_caches()
    from strata.api.main import create_app

    with TestClient(create_app()) as c:
        codes = [c.get(f"{V}/examples").status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and codes[-1] == 429
    reset_platform_caches()
