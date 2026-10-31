#!/usr/bin/env python
"""Generate the worked f-statistic examples under `data/examples/`.

Every example is a **real computation**. Nothing here fabricates numbers: if
ADMIXTOOLS 2 is unavailable the script exits non-zero and writes nothing, so a
missing example directory means "not yet computed", never "made up".

    # from the repository root, with STRATA_RSCRIPT pointing at the R env
    python data/examples/generate_examples.py

The examples run on `admixtools::example_f2_blocks`, the f2 blocks bundled with
ADMIXTOOLS 2. Those are genuine f2-statistics for seven populations — Altai
Neanderthal, Vindija, Denisova, Mbuti, Chimp, Russia_Ust_Ishim and
Switzerland_Bichon — so the statistics computed from them are real. They are
the package's demonstration populations: archaic hominins and Palaeolithic
modern humans. **They are not a South Asian analysis**, and every example
record says so in its own `description` and `caveats`.

South Asian examples require the AADR reference panel, which the pipeline in
`data/pipeline/` builds on a machine that can reach Harvard Dataverse.

Output layout (agreed with the API workstream) — one file per example:

    data/examples/<slug>/example.json
      {slug, title, summary, kind, result_kind, tags[], description,
       caveats[], inputs{}, params{}, result{}, provenance{}}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from strata.qpadm import (
    F4Spec,
    QpAdmRotateSpec,
    QpAdmSpec,
    QpWaveSpec,
    admixtools_version,
    qpadm_available,
    r_script_dir,
    rscript_path,
    run_f4,
    run_qpadm,
    run_qpadm_rotate,
    run_qpwave,
    summarize_rotation,
)

TARGET = "Denisova.DG"
NEANDERTHALS = ["Altai_Neanderthal.DG", "Vindija.DG"]
DEEP_RIGHT = [
    "Chimp.REF",
    "Mbuti.DG",
    "Russia_Ust_Ishim.DG",
    "Switzerland_Bichon.SG",
]

DATA_CAVEAT = (
    "Computed from admixtools::example_f2_blocks, the f2-statistics bundled with "
    "ADMIXTOOLS 2 for seven populations (Altai Neanderthal, Vindija, Denisova, "
    "Mbuti, Chimp, Russia_Ust_Ishim, Switzerland_Bichon). These are real data and "
    "the statistics are genuine, but they are the package's demonstration "
    "populations -- archaic hominins and Palaeolithic modern humans. This is NOT a "
    "South Asian analysis and must not be presented as one. South Asian examples "
    "require the AADR reference panel built by data/pipeline/."
)

FORMAL_CAVEAT_NOTE = (
    "qpAdm does not identify the true history. A model that is not rejected is "
    "consistent with these data given this outgroup set; other untested models may "
    "fit as well or better. p-values depend on the right populations, the SNP set "
    "and the jackknife block size."
)


def sha256_of(payload: Any) -> str:
    """Stable hash of a JSON-serialisable object."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


@dataclass
class Example:
    slug: str
    title: str
    summary: str
    kind: str
    description: str
    params: dict[str, Any]
    result: dict[str, Any]
    tags: list[str]
    command: str
    extra_caveats: list[str]


def export_example_f2(dest: Path) -> dict[str, Any]:
    """Write `admixtools::example_f2_blocks` to an f2 cache and return its metadata."""
    script = r_script_dir() / "export_example_f2.R"
    exe = rscript_path()
    if exe is None or not script.is_file():
        raise RuntimeError(f"cannot export example f2 blocks: missing {exe or script}")
    proc = subprocess.run(
        [exe, "--vanilla", str(script), str(dest)],
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"export_example_f2.R failed:\n{proc.stderr[-4000:]}")
    meta_path = dest / "strata_export.json"
    return json.loads(meta_path.read_text(encoding="utf-8"))


def build_examples(f2_dir: Path) -> list[Example]:
    """Run every example analysis. Each call is a real ADMIXTOOLS 2 computation."""
    examples: list[Example] = []

    # 1. Two-source qpAdm: the documented model for this dataset.
    spec = QpAdmSpec(
        target=TARGET, left=NEANDERTHALS, right=DEEP_RIGHT, f2_dir=str(f2_dir)
    )
    result = run_qpadm(spec)
    examples.append(
        Example(
            slug="qpadm-denisova-two-neanderthal-sources",
            title="qpAdm: Denisova modelled from two Neanderthals",
            summary=(
                f"Two-source qpAdm fit for {TARGET}; "
                f"p = {result.p:.3g}, verdict "
                f"{result.feasibility.verdict if result.feasibility else 'n/a'}."
            ),
            kind="qpadm",
            description=(
                "Models Denisova.DG as a mixture of Altai Neanderthal and Vindija "
                "relative to four deep outgroups. This is the worked example from "
                "ADMIXTOOLS 2's own qpadm() documentation, so the output can be "
                "checked directly against the upstream package. It is a useful "
                "demonstration of what a *rejected* model looks like: Denisovans "
                "are a sister lineage to Neanderthals, not a mixture of two of "
                "them, so the fit statistic is expected to be poor. Read the "
                "rank-drop table and the weight standard errors, not just the "
                "point estimates."
            ),
            params=spec.model_dump(mode="json", exclude_none=True),
            result=result.model_dump(mode="json"),
            tags=["qpadm", "formal", "archaic", "demonstration", "two-source"],
            command="run_qpadm(QpAdmSpec(...))",
            extra_caveats=[FORMAL_CAVEAT_NOTE],
        )
    )

    # 2. One-source qpAdm: a cladality test, for contrast with the two-source fit.
    spec1 = QpAdmSpec(
        target=TARGET, left=["Vindija.DG"], right=DEEP_RIGHT, f2_dir=str(f2_dir)
    )
    result1 = run_qpadm(spec1)
    examples.append(
        Example(
            slug="qpadm-denisova-single-source",
            title="qpAdm: Denisova from a single source (cladality test)",
            summary=(
                f"Single-source qpAdm for {TARGET} from Vindija; "
                f"p = {result1.p:.3g}."
            ),
            kind="qpadm",
            description=(
                "With one source the model has rank 0 and the weight is fixed at 1 "
                "by construction, so the only thing being tested is whether target "
                "and source form a clade relative to the outgroups. Comparing this "
                "with the two-source fit shows why a weight vector on its own says "
                "nothing: the weight here is 100% regardless of how badly the "
                "model fits."
            ),
            params=spec1.model_dump(mode="json", exclude_none=True),
            result=result1.model_dump(mode="json"),
            tags=["qpadm", "formal", "archaic", "cladality", "single-source"],
            command="run_qpadm(QpAdmSpec(...))",
            extra_caveats=[FORMAL_CAVEAT_NOTE],
        )
    )

    # 3. Rotating qpAdm over a candidate pool.
    rot_spec = QpAdmRotateSpec(
        target=TARGET,
        leftright=[
            "Altai_Neanderthal.DG",
            "Vindija.DG",
            "Russia_Ust_Ishim.DG",
            "Switzerland_Bichon.SG",
        ],
        rightfix=["Chimp.REF", "Mbuti.DG"],
        max_sources=2,
        f2_dir=str(f2_dir),
    )
    rot = run_qpadm_rotate(rot_spec)
    examples.append(
        Example(
            slug="qpadm-rotate-denisova-candidates",
            title="Rotating qpAdm: every one- and two-source model",
            summary=(
                f"{rot.n_models_tested} models fitted for {TARGET}; "
                + summarize_rotation(rot.models).split(".")[0]
                + "."
            ),
            kind="qpadm_rotate",
            description=(
                "Rotates four candidate populations between the source and outgroup "
                "roles, pinning Chimp and Mbuti to the right, and fits every "
                "resulting one- and two-source model. Models are ranked by p-value, "
                "best first.\n\n"
                "The ranking is a shortlist, not a result. All of these models were "
                "fitted on the same SNPs, so their p-values are not independent and "
                "no multiple-testing correction has been applied. When several "
                "models fit at once, the honest conclusion is that these data "
                "cannot distinguish between them.\n\n"
                + summarize_rotation(rot.models)
            ),
            params=rot_spec.model_dump(mode="json", exclude_none=True),
            result=rot.model_dump(mode="json"),
            tags=["qpadm", "qpadm_rotate", "formal", "archaic", "model-search"],
            command="run_qpadm_rotate(QpAdmRotateSpec(...))",
            extra_caveats=[FORMAL_CAVEAT_NOTE, rot.rotation_caveat],
        )
    )

    # 4. f4 symmetry tests.
    f4_spec = F4Spec(
        pop1=["Chimp.REF"],
        pop2=["Mbuti.DG"],
        pop3=["Altai_Neanderthal.DG", "Vindija.DG", "Denisova.DG"],
        pop4=["Russia_Ust_Ishim.DG"],
        f2_dir=str(f2_dir),
    )
    f4 = run_f4(f4_spec)
    significant = [r for r in f4.f4 if r.z is not None and abs(r.z) >= 3]
    examples.append(
        Example(
            slug="f4-archaic-symmetry-tests",
            title="f4 symmetry tests against the archaic lineages",
            summary=(
                f"{f4.n_statistics} f4-statistics; "
                f"{len(significant)} with |Z| >= 3."
            ),
            kind="f4",
            description=(
                "f4(Chimp, Mbuti; X, Russia_Ust_Ishim) for each archaic X. f4 is "
                "zero in expectation when the Chimp/Mbuti split is unrelated to the "
                "X/Ust-Ishim split; a significantly non-zero value indicates shared "
                "drift between one population on each side.\n\n"
                "|Z| >= 3 is the conventional threshold, roughly p = 0.003 two-sided "
                "before any correction for the number of statistics computed here. "
                "The standard errors come from a block jackknife over 5 cM blocks, "
                "which accounts for linkage between nearby SNPs; a naive per-SNP "
                "standard error would be far too small."
            ),
            params=f4_spec.model_dump(mode="json", exclude_none=True),
            result=f4.model_dump(mode="json"),
            tags=["f4", "formal", "archaic", "symmetry"],
            command="run_f4(F4Spec(...))",
            extra_caveats=[
                (
                    "Several f4-statistics are computed from one dataset, so the "
                    "per-statistic p-values are not corrected for multiple testing."
                )
            ],
        )
    )

    # 5. qpWave: how many waves separate the two sets.
    qw_spec = QpWaveSpec(left=NEANDERTHALS, right=DEEP_RIGHT, f2_dir=str(f2_dir))
    qw = run_qpwave(qw_spec)
    examples.append(
        Example(
            slug="qpwave-neanderthal-ranks",
            title="qpWave: admixture-wave lower bound for the Neanderthals",
            summary=(
                "Rank test for two Neanderthals against four outgroups; smallest "
                f"rank not rejected: {qw.min_rank_not_rejected}."
            ),
            kind="qpwave",
            description=(
                "Fits low-rank approximations to the matrix of f4-statistics "
                "between the two Neanderthal genomes and the four outgroups. The "
                "rank-0 test asks whether the two sets form two clades relative to "
                "each other; the smallest rank that is not rejected is a *lower "
                "bound* on the number of admixture waves, not an estimate of it. "
                "A lower bound of 1 does not mean exactly one wave occurred."
            ),
            params=qw_spec.model_dump(mode="json", exclude_none=True),
            result=qw.model_dump(mode="json"),
            tags=["qpwave", "formal", "archaic", "rank-test"],
            command="run_qpwave(QpWaveSpec(...))",
            extra_caveats=[
                (
                    "qpWave reports a lower bound on the number of admixture waves. "
                    "Failing to reject a rank is not evidence that the rank is correct."
                )
            ],
        )
    )

    return examples


def write_examples(
    examples: list[Example], out_root: Path, f2_meta: dict[str, Any]
) -> list[Path]:
    written: list[Path] = []
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    at_version = admixtools_version()

    for ex in examples:
        provenance = {
            "engine": "ADMIXTOOLS 2",
            "admixtools_version": at_version,
            "r_version": (ex.result.get("provenance") or {}).get("r_version_string"),
            "platform": platform.platform(),
            "python_version": sys.version.split()[0],
            "command": ex.command,
            "generated_at": now,
            "generator": "data/examples/generate_examples.py",
            "f2_source": f2_meta.get("source"),
            "f2_n_pops": f2_meta.get("n_pops"),
            "f2_n_blocks": f2_meta.get("n_blocks"),
            "f2_n_snps": f2_meta.get("n_snps"),
            "f2_roundtrip_max_abs_diff": f2_meta.get("roundtrip_max_abs_diff"),
            "params_sha256": sha256_of(ex.params),
            "result_sha256": sha256_of(ex.result),
            "citations": [
                (
                    "Maier, R., Flegontov, P., Flegontova, O., Isildak, U., "
                    "Changmai, P., & Reich, D. (2023). On the limits of fitting "
                    "complex models of population history to f-statistics. "
                    "eLife, 12, e85492. https://doi.org/10.7554/eLife.85492"
                )
            ],
        }
        record = {
            "slug": ex.slug,
            "title": ex.title,
            "summary": ex.summary,
            "kind": ex.kind,
            "result_kind": "formal",
            "tags": ex.tags,
            "description": ex.description,
            "caveats": [DATA_CAVEAT, *ex.extra_caveats],
            "inputs": {
                "f2_source": "admixtools::example_f2_blocks",
                "f2_populations": f2_meta.get("pops", []),
                "synthetic": False,
                "note": (
                    "Real f2-statistics bundled with ADMIXTOOLS 2. No genotype data "
                    "is redistributed by this example."
                ),
            },
            "params": ex.params,
            "result": ex.result,
            "provenance": provenance,
        }
        directory = out_root / ex.slug
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "example.json"
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "data" / "examples",
        help="output root (default: data/examples)",
    )
    ap.add_argument(
        "--keep-f2",
        type=Path,
        default=None,
        help="keep the exported example f2 cache at this path instead of a temp dir",
    )
    args = ap.parse_args(argv)

    if not qpadm_available():
        print(
            "error: ADMIXTOOLS 2 is not available, so no example can be computed.\n"
            "       Run services/worker/r/install_env.sh and set STRATA_RSCRIPT.\n"
            "       Nothing was written: an absent example means 'not yet computed',\n"
            "       never a fabricated result.",
            file=sys.stderr,
        )
        return 2

    with tempfile.TemporaryDirectory(prefix="strata-examples-") as tmp:
        f2_dir = args.keep_f2 or (Path(tmp) / "f2")
        print(f"exporting example f2 blocks to {f2_dir}", file=sys.stderr)
        f2_meta = export_example_f2(f2_dir)
        print(
            f"  {f2_meta['n_pops']} populations, {f2_meta['n_blocks']} blocks, "
            f"{f2_meta['n_snps']} SNPs",
            file=sys.stderr,
        )
        examples = build_examples(f2_dir)
        written = write_examples(examples, args.out, f2_meta)

    for path in written:
        print(path.relative_to(REPO_ROOT))
    print(f"\n{len(written)} example(s) written.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
