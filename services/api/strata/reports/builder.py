"""Reproducible analysis reports: a canonical JSON bundle and an HTML rendering of it.

The JSON bundle is the source of truth; the HTML is a deterministic rendering of the bundle.
`bundle_sha256` is the SHA-256 of the canonical JSON (sorted keys, no whitespace) of the
bundle without that field, so a reader can verify the file was not altered.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

REPORT_VERSION = "strata-report-v1"

EXPLORATORY_CAVEATS = [
    "This is an exploratory fit in a reduced coordinate space (PCA / G25-style). It "
    "summarises genetic similarity; it is not a formal test of an admixture model.",
    "Mixture weights in coordinate space are sensitive to the choice of sources, to "
    "projection shrinkage and to the dimensions used. Small distances do not imply that "
    "the sources are the true ancestral populations.",
    "Populations are reference labels for sampled individuals, not ethnic identities.",
    "Confirm candidate models with formal f-statistics tests (qpAdm) before drawing "
    "conclusions.",
]
FORMAL_CAVEATS = [
    "qpAdm tests whether the target is consistent with a mixture of the left populations "
    "relative to the right (outgroup) set; a non-rejected model (p above threshold) is "
    "consistent with the data, not proven.",
    "Results depend on the right-population set; models should be checked by rotating "
    "outgroups and examining feasibility (weights within [0, 1]) and standard errors.",
    "Low SNP counts, related individuals, contamination and pseudo-haploid low-coverage "
    "data can bias f-statistics.",
]

_TEMPLATES = Path(__file__).with_name("templates")
_env = Environment(loader=FileSystemLoader(_TEMPLATES),
                   autoescape=select_autoescape(["html", "j2"]),
                   trim_blocks=True, lstrip_blocks=True)


def _fmt(v: Any, digits: int = 4) -> str:
    if v is None:
        return "–"
    if isinstance(v, float):
        if v != 0 and (abs(v) < 1e-3 or abs(v) >= 1e5):
            return f"{v:.{digits - 1}e}"
        return f"{v:.{digits}f}"
    return str(v)


_env.filters["fmt"] = _fmt
_env.filters["pct"] = lambda v: "–" if v is None else f"{100 * float(v):.1f}%"
_env.filters["tojson_pretty"] = lambda v: json.dumps(v, indent=2, sort_keys=True, default=str)


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str,
                      ensure_ascii=False).encode()


def classification(kind: str, result: dict[str, Any] | None) -> str:
    if result and result.get("kind") in ("exploratory", "formal"):
        return str(result["kind"])
    return "formal" if kind.startswith("qpadm") else "exploratory"


def _uncertainty(result: dict[str, Any]) -> dict[str, Any]:
    """Collect the uncertainty measures present in a result, without inventing any."""
    out: dict[str, Any] = {}
    weights = result.get("weights")
    if isinstance(weights, list) and weights and isinstance(weights[0], dict):
        rows = []
        for w in weights:
            row = {"source": w.get("source") or w.get("name"), "weight": w.get("weight")}
            for k in ("se", "ci_low", "ci_high", "z"):
                if w.get(k) is not None:
                    row[k] = w[k]
            rows.append(row)
        out["weights"] = rows
    for k in ("n_bootstrap", "p_value", "chisq", "dof", "distance", "feasible", "n_snps",
              "n_snps_used", "sensitivity"):
        if result.get(k) is not None:
            out[k] = result[k]
    if not out:
        out["note"] = "This analysis type reports no sampling uncertainty."
    return out


def _reproduce_steps(bundle: dict[str, Any]) -> list[str]:
    a = bundle["analysis"]
    code = bundle["provenance"].get("code", {})
    ref = bundle["provenance"].get("reference_version")
    commit = code.get("git_sha") or f"(release {code.get('strata')})"
    steps = [
        f"Check out Strata at commit {commit} and install services/api "
        "(`uv pip install -e services/api`).",
        f"Build or download the reference data version {ref or '(none used)'} "
        "(data/pipeline, verify data/derived/MANIFEST.json sha256 sums).",
    ]
    for inp in bundle["inputs"]:
        steps.append(
            f"Upload the input file whose SHA-256 is {inp['input_sha256']} "
            f"(dataset kind {inp['kind']}); the harmonised payload must hash to "
            f"{inp['payload_sha256']}."
        )
    steps.append(
        "POST /api/v1/analyses with the request body in `reproduce.api_request` "
        "(replace dataset_id with the new dataset id)."
    )
    if bundle["provenance"].get("seed") is not None:
        steps.append(f"The random seed {bundle['provenance']['seed']} is part of the "
                     "parameters; results are deterministic given the same inputs.")
    steps.append(f"Compare the result with `results` in this bundle (analysis kind {a['kind']}).")
    return steps


def build_bundle(analysis: Any, datasets: list[Any], *, generated_at: datetime) -> dict[str, Any]:
    result = analysis.result or {}
    cls = classification(analysis.kind, result)
    caveats = list(EXPLORATORY_CAVEATS if cls == "exploratory" else FORMAL_CAVEATS)
    if isinstance(result.get("caveat"), str) and result["caveat"] not in caveats:
        caveats.insert(0, result["caveat"])
    for n in result.get("notes", []) or []:
        caveats.append(str(n))
    inputs = [{
        "dataset_id": str(d.id), "name": d.name, "kind": d.kind,
        "input_sha256": d.input_sha256, "payload_sha256": d.payload_sha256,
        "payload_format": d.payload_format, "panel_version": d.panel_version,
        "qc": {k: d.qc_report.get(k) for k in ("vendor", "build", "n_variants", "call_rate",
                                               "panel_overlap", "n_samples", "n_dims",
                                               "scaled") if k in d.qc_report},
    } for d in datasets]
    params = dict(analysis.params or {})
    api_request = {"kind": analysis.kind, "title": analysis.title,
                   "dataset_id": str(analysis.dataset_ids[0]) if analysis.dataset_ids else None,
                   "target": params.pop("target", None), "params": params}
    bundle: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "generated_at": generated_at.isoformat(),
        "analysis": {"id": str(analysis.id), "kind": analysis.kind, "title": analysis.title,
                     "status": analysis.status,
                     "created_at": analysis.created_at.isoformat(),
                     "finished_at": analysis.finished_at.isoformat()
                     if analysis.finished_at else None},
        "classification": cls,
        "inputs": inputs,
        "parameters": analysis.params or {},
        "provenance": analysis.provenance or {},
        "results": result,
        "uncertainty": _uncertainty(result),
        "caveats": caveats,
    }
    bundle["reproduce"] = {"steps": _reproduce_steps(bundle), "api_request": api_request}
    bundle["bundle_sha256"] = hashlib.sha256(canonical_json(bundle)).hexdigest()
    return bundle


def verify_bundle(bundle: dict[str, Any]) -> bool:
    body = {k: v for k, v in bundle.items() if k != "bundle_sha256"}
    return hashlib.sha256(canonical_json(body)).hexdigest() == bundle.get("bundle_sha256")


def render_html(bundle: dict[str, Any]) -> str:
    return _env.get_template("report.html.j2").render(b=bundle)
