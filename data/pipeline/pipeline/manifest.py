"""MANIFEST.json: what was built, from what, and with which checksums.

The manifest is the only thing that makes a derived artefact reviewable. It
records the AADR release and the sha256 of every source file, the sha256 of
every artefact written, the QC thresholds and exclusion counts, the pipeline
and tool versions, and the licensing pointer. `ReferenceLibrary.version` reads
its `version` field.
"""

from __future__ import annotations

import datetime as dt
import json
import platform
import sys
from pathlib import Path
from typing import Any

from .config import (
    AADR_CITATIONS,
    AADR_DOI,
    ADMIXTOOLS2_CITATION,
    PIPELINE_VERSION,
    SCHEMA_VERSION,
)
from .download import sha256_file

MANIFEST_NAME = "MANIFEST.json"

# Artefacts small enough and free enough of genotype content to commit.
COMMITTABLE = (
    "populations.parquet",
    "samples.parquet",
    "publications.parquet",
    "spaces.json",
    "MANIFEST.json",
)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows_in(path: Path) -> int | None:
    if path.suffix != ".parquet":
        return None
    try:
        import pyarrow.parquet as pq

        return int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:  # noqa: BLE001 - row count is informational only
        return None


def describe_artefact(path: Path, root: Path) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    entry: dict[str, Any] = {
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "committed": rel in COMMITTABLE,
    }
    rows = _rows_in(path)
    if rows is not None:
        entry["rows"] = rows
    return entry


def scan_artefacts(root: Path, *, skip_dirs: tuple[str, ...] = ("f2",)) -> dict[str, Any]:
    """Hash every file under `root`, skipping directories that are rebuilt.

    f2 caches hold thousands of small `.rds` files; hashing them individually
    would bloat the manifest without adding anything the cache's own
    `cache_id` does not already give.
    """
    out: dict[str, Any] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        rel_parts = path.relative_to(root).parts
        if rel_parts and rel_parts[0] in skip_dirs:
            continue
        out[path.relative_to(root).as_posix()] = describe_artefact(path, root)
    return out


def build_manifest(
    *,
    root: Path,
    version: str,
    aadr_version: str,
    sources: list[dict[str, Any]],
    counts: dict[str, Any],
    qc: dict[str, Any],
    exclusions: dict[str, Any],
    spaces: list[dict[str, Any]],
    f2: dict[str, Any] | None = None,
    panel: dict[str, Any] | None = None,
    tools: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the manifest dictionary (does not write it)."""
    return {
        "version": version,
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "built_at": utc_now(),
        "aadr_version": aadr_version,
        "aadr_doi": AADR_DOI,
        "sources": sources,
        "counts": counts,
        "qc_thresholds": qc,
        "exclusions": exclusions,
        "panel": panel or {},
        "spaces": [
            {"id": s["id"], "n_dims": s["n_dims"], "level": s["level"]} for s in spaces
        ],
        "f2": f2 or {},
        "tools": tools
        or {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "citations": {
            "aadr": list(AADR_CITATIONS),
            "admixtools2": ADMIXTOOLS2_CITATION,
        },
        "licensing": (
            "AADR data is redistributed only as derived metadata and coordinates. "
            "See docs/DATA_PROVENANCE.md for terms, citation requirements and the "
            "individuals excluded from public release."
        ),
        "notes": notes or [],
        "artefacts": {},
    }


def write_manifest(manifest: dict[str, Any], root: Path) -> Path:
    """Write the manifest after hashing every artefact beside it."""
    root.mkdir(parents=True, exist_ok=True)
    manifest = dict(manifest)
    manifest["artefacts"] = scan_artefacts(root)
    path = root / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return path


def verify_manifest(root: Path) -> dict[str, list[str]]:
    """Re-hash the artefacts a manifest describes.

    Returns a report with `ok`, `changed` and `missing` lists. Used by CI to
    prove that a committed manifest still describes the committed files.
    """
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise FileNotFoundError(f"no {MANIFEST_NAME} in {root}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    report: dict[str, list[str]] = {"ok": [], "changed": [], "missing": []}
    for rel, entry in (manifest.get("artefacts") or {}).items():
        target = root / rel
        if not target.is_file():
            report["missing"].append(rel)
        elif sha256_file(target) == entry.get("sha256"):
            report["ok"].append(rel)
        else:
            report["changed"].append(rel)
    return report
