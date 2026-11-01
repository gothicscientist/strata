"""Exercise the deployed stack using clearly synthetic, disposable guest data.

No user DNA or provider key is used. Writes a public-safe verification report;
guest credentials stay in memory. Run from the repository root after deployment.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="https://api.stratalab.cc")
    p.add_argument("--output", default=".deployment/live-verification.json")
    a = p.parse_args()
    client = httpx.Client(base_url=a.url.rstrip("/") + "/api/v1/", timeout=180)
    results: list[dict] = []
    datasets: list[str] = []
    analyses: list[dict] = []
    comparisons: list[str] = []
    sessions: list[str] = []

    def request(method: str, path: str, expected=200, **kwargs):
        r = client.request(method, path, **kwargs)
        if r.status_code != expected:
            raise AssertionError(f"{method} {path}: {r.status_code}: {r.text[:1200]}")
        return r

    def record(name: str, **details) -> None:
        results.append({"check": name, "passed": True, **details})
        Path(a.output).write_text(
            json.dumps({"url": a.url, "results": results}, indent=2)
        )
        print(name, "PASS", json.dumps(details), flush=True)

    health = request("GET", "health").json()
    caps = health["capabilities"]
    assert health["status"] == "ok"
    assert all(
        caps[k] for k in ["reference_loaded", "snp_panel_loaded", "qpadm", "llm_byok"]
    )
    assert caps["job_mode"] == "queue" and caps["database"] == "postgres"
    record("health", capabilities=caps)
    for path in [
        "reference/populations",
        "reference/spaces",
        "reference/publications",
        "reference/panel",
        "examples",
    ]:
        assert request("GET", path).json()
    examples = request("GET", "examples").json()
    for example in examples:
        assert request("GET", f"examples/{example['slug']}").json()["result"]
    record("reference library and all worked examples", examples=len(examples))
    guest = request("POST", "auth/guest", 201).json()
    client.headers["Authorization"] = f"Bearer {guest['token']}"
    other = httpx.Client(base_url=client.base_url, timeout=180)
    other_guest = other.post("auth/guest").json()
    other.headers["Authorization"] = f"Bearer {other_guest['token']}"
    assert request("GET", "auth/me").json()["kind"] == "guest"

    def upload(name: str, text: str, kind="g25") -> dict:
        ds = request(
            "POST",
            "datasets",
            201,
            data={"name": "DEPLOYMENT TEST — " + name, "kind": kind},
            files={"file": (name + (".csv" if kind == "g25" else ".txt"), text)},
        ).json()
        datasets.append(ds["id"])
        return ds

    def analyse(
        kind: str, params: dict, dataset: str | None = None, target: str | None = None
    ) -> dict:
        start = time.monotonic()
        created = request(
            "POST",
            "analyses",
            201,
            json={
                "kind": kind,
                "title": "DEPLOYMENT TEST — " + kind,
                "dataset_id": dataset,
                "target": target,
                "params": params,
            },
        ).json()
        analysis = created["analysis"]
        analyses.append(analysis)
        while time.monotonic() - start < 900:
            analysis = request("GET", f"analyses/{analysis['id']}").json()
            if analysis["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(5)
        assert analysis["status"] == "succeeded", analysis.get(
            "error", analysis["status"]
        )
        assert analysis["result"] and analysis["provenance"]["reference_version"]
        assert other.get(f"analyses/{analysis['id']}").status_code == 404
        bundle = request("GET", f"analyses/{analysis['id']}/report?format=json").json()
        from strata.reports import verify_bundle

        assert verify_bundle(bundle)
        assert (
            request("GET", f"analyses/{analysis['id']}/report")
            .headers["content-type"]
            .startswith("text/html")
        )
        record(
            kind,
            seconds=round(time.monotonic() - start, 1),
            classification=analysis["result"]["kind"],
            analysis_id=analysis["id"],
        )
        return analysis

    try:
        rng = np.random.default_rng(20261101)
        source_vectors = rng.normal(0, 0.02, (2, 25))

        def line(name, vector):
            return name + "," + ",".join(f"{x:.9f}" for x in vector)

        source = upload(
            "synthetic-sources",
            "\n".join(
                line(f"SyntheticSource{i}", v) for i, v in enumerate(source_vectors)
            ),
        )
        target = upload(
            "synthetic-target",
            line("SyntheticTarget", 0.6 * source_vectors[0] + 0.4 * source_vectors[1]),
        )
        assert other.get(f"datasets/{target['id']}").status_code == 404
        request("GET", f"datasets/{target['id']}")
        record("G25 uploads and owner isolation")
        fit = analyse(
            "admixture_fit",
            {"source_dataset_id": source["id"], "bootstrap": 0, "seed": 1},
            target["id"],
        )
        assert abs(fit["result"]["weights"][0]["weight"] - 0.6) < 0.001
        rotate = analyse(
            "admixture_rotate",
            {"source_dataset_id": source["id"], "k_min": 1, "k_max": 2},
            target["id"],
        )
        comparison = request(
            "POST",
            "comparisons",
            201,
            json={"name": "DEPLOYMENT TEST", "analysis_ids": [fit["id"], rotate["id"]]},
        ).json()
        comparisons.append(comparison["id"])
        assert any(
            c["id"] == comparison["id"] and c["summary"]
            for c in request("GET", "comparisons").json()
        )
        assert not other.get("comparisons").json()
        assert other.delete(f"comparisons/{comparison['id']}").status_code == 404
        record("comparison and report bundles")

        panel = pd.read_parquet("data/derived/snp_panel.parquet").iloc[::5].head(30000)
        lines = [
            "# This is synthetic deployment-test data, not a person's genome.",
            "# 23andMe raw data, genome build 37",
            "# rsid\tchromosome\tposition\tgenotype",
        ]
        for row in panel.itertuples():
            genotype = row.ref + row.alt
            lines.append(f"{row.rsid}\t{row.chrom}\t{row.pos}\t{genotype}")
        raw = upload("synthetic-raw-dna", "\n".join(lines), "raw_dna")
        assert raw["summary"]["harmonized"]
        assert raw["qc"]["overlap"]["n_usable"] > 10000
        projected = analyse("pca_project", {}, raw["id"])
        assert projected["result"]["n_snps_used"] > 10000
        analyse("nearest", {"k": 5}, raw["id"])
        record(
            "raw DNA harmonization and projection",
            usable_snps=raw["qc"]["overlap"]["n_usable"],
        )

        right = ["Mbuti", "Han", "Papuan", "Mixe", "Russia_UstIshim_IUP"]
        analyse(
            "qpadm",
            {"left": ["Iran_GanjDareh_N"], "right": right},
            target="Iran_HajjiFiruz_N",
        )
        analyse(
            "qpadm_rotate",
            {
                "candidates": ["Iran_GanjDareh_N", "Iran_SehGabi_C"],
                "right": right,
                "min_sources": 1,
                "max_sources": 1,
            },
            target="Iran_HajjiFiruz_N",
        )
        session = request(
            "POST", "chat/sessions", 201, json={"title": "DEPLOYMENT TEST"}
        ).json()
        sessions.append(session["id"])
        assert request("GET", f"chat/sessions/{session['id']}").json()
        assert other.get(f"chat/sessions/{session['id']}").status_code == 404
        missing_key = client.post(
            f"chat/sessions/{session['id']}/messages", json={"content": "test"}
        )
        assert missing_key.status_code == 503
        record("chat sessions and explicit BYOK requirement")
    finally:
        for sid in sessions:
            request("DELETE", f"chat/sessions/{sid}", 204)
        for cid in comparisons:
            request("DELETE", f"comparisons/{cid}", 204)
        for analysis in analyses:
            request("DELETE", f"analyses/{analysis['id']}", 204)
        for did in datasets:
            request("DELETE", f"datasets/{did}", 204)
            assert client.get(f"datasets/{did}").status_code == 404
        record("synthetic test data deleted")
        other.close()
        client.close()


if __name__ == "__main__":
    main()
