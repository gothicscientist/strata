"""`python -m pipeline` — the AADR reference build.

Stages are separate subcommands and each is idempotent, so a build that dies
part-way resumes by rerunning the same command. The intended order is:

    python -m pipeline download            # AADR 1240K + HO from Dataverse
    python -m pipeline curate              # .anno -> populations/samples parquet
    python -m pipeline pca                 # fit strata-pca-v1, project everyone
    python -m pipeline f2                  # ADMIXTOOLS 2 f2 block cache
    python -m pipeline manifest            # hash everything
    python -m pipeline all                 # the above in order

`inspect-anno` resolves a release's header without building anything, which is
the first thing to run after an AADR version bump.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from . import curate as curate_mod
from . import manifest as manifest_mod
from . import panel as panel_mod
from .anno import header_report, read_anno
from .config import (
    AADR_CITATIONS,
    AADR_DOI,
    AADR_VERSION,
    DATASETS,
    F2,
    PCA_SPACE,
    QC,
    REFERENCE_VERSION,
    RETIRED_AADR_VERSIONS,
    BuildContext,
    paths,
)
from .schema import (
    PublicationRow,
    write_coordinates,
    write_populations,
    write_publications,
    write_samples,
    write_spaces,
)

log = logging.getLogger("pipeline")


def _ensure_release_is_current(version: str) -> None:
    """Refuse to build from a decommissioned AADR release.

    v62.0 and v66.0 were withdrawn because they contained data from 161
    present-day individuals that is only available through the EGA data access
    committee. Building from them would redistribute that data.
    """
    if version in RETIRED_AADR_VERSIONS:
        raise SystemExit(
            f"AADR {version} has been decommissioned by the Reich Lab because it "
            "contained data that should not have been public (161 individuals from "
            "Jacobs et al. 2019, EGA accession EGAS00001003054). Use v62.0.p1 or "
            "v66.p1 instead. See docs/DATA_PROVENANCE.md."
        )


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------


def cmd_inspect_anno(args: argparse.Namespace) -> int:
    report = header_report(args.path)
    print(json.dumps(report, indent=2))
    if report["unmapped"]:
        print(
            f"\n{len(report['unmapped'])} column(s) were not recognised; they are kept "
            "under their normalised names. Add a ColumnRule in pipeline/anno.py if the "
            "pipeline needs one of them.",
            file=sys.stderr,
        )
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    from .download import DownloadError, fetch_dataset, fetch_listing

    _ensure_release_is_current(args.aadr_version)
    p = paths(args.root)
    keys = args.datasets or list(DATASETS)
    base = p.raw / "aadr" / args.aadr_version
    base.mkdir(parents=True, exist_ok=True)

    try:
        listing = fetch_listing(AADR_DOI, base, refresh=args.refresh_listing)
    except DownloadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out: dict[str, Any] = {}
    for key in keys:
        dataset = DATASETS[key]
        dest = p.aadr_dir(key)
        log.info("fetching AADR %s %s -> %s", args.aadr_version, key, dest)
        try:
            result = fetch_dataset(dataset, dest, listing=listing)
        except DownloadError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        out[key] = {"directory": str(result.directory), "files": result.files}
        for note in result.notes:
            log.info("%s: %s", key, note)

    (base / "download.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


def _publication_rows(samples: list[curate_mod.CuratedSample]) -> list[PublicationRow]:
    """Publication stubs from the `.anno` Publication keys.

    AADR gives a short citation key, not a full reference. The key is kept as
    the id and citation so the library has something stable to join on;
    enriching it with DOIs is a separate, optional step and is deliberately
    not faked here.
    """
    keys = sorted({s.publication_id for s in samples if s.publication_id})
    return [
        PublicationRow(
            id=k,
            citation=f"AADR publication key: {k}",
            year=None,
            doi=None,
            url=None,
        )
        for k in keys
    ]


def cmd_curate(args: argparse.Namespace) -> int:
    _ensure_release_is_current(args.aadr_version)
    p = paths(args.root)
    ctx = BuildContext(paths=p, aadr_version=args.aadr_version)

    # The 1240K release drives the panel: it is what f-statistics run on.
    # HO adds the present-day individuals that define the PCA space.
    primary = DATASETS["1240K"]
    secondary = DATASETS["HO"]
    anno_1240k = p.aadr_dir("1240K") / primary.anno
    anno_ho = p.aadr_dir("HO") / secondary.anno

    if not anno_1240k.is_file():
        print(
            f"error: {anno_1240k} not found. Run `python -m pipeline download` first.",
            file=sys.stderr,
        )
        return 2

    records_1240k = read_anno(anno_1240k)
    log.info("parsed %d rows from %s", len(records_1240k), anno_1240k.name)
    records_ho = read_anno(anno_ho) if anno_ho.is_file() else []
    if records_ho:
        log.info("parsed %d rows from %s", len(records_ho), anno_ho.name)
    else:
        ctx.note(f"{anno_ho.name} absent; PCA space cannot be built from this run")

    all_groups = [r.group_id for r in records_1240k] + [r.group_id for r in records_ho]
    resolution = panel_mod.resolve(all_groups)
    log.info(
        "panel resolved: %d groups matched, %d requested labels unmatched",
        len(resolution.matched),
        len(resolution.unmatched),
    )
    if resolution.unmatched:
        ctx.note(
            f"{len(resolution.unmatched)} panel labels matched nothing in "
            f"AADR {args.aadr_version}: {', '.join(sorted(resolution.unmatched)[:20])}"
            + (" ..." if len(resolution.unmatched) > 20 else "")
        )

    keep = set(resolution.matched) if not args.all_groups else None

    samples_1240k, log_1240k = curate_mod.curate_samples(
        records_1240k,
        snpset="1240K",
        keep_groups=keep,
        roles=resolution.roles,
        blocks=resolution.matched,
    )
    samples_ho, log_ho = curate_mod.curate_samples(
        records_ho,
        snpset="HO",
        keep_groups=keep,
        roles=resolution.roles,
        blocks=resolution.matched,
    )
    log.info("curated: %d (1240K), %d (HO)", len(samples_1240k), len(samples_ho))

    # One row per individual. 1240K wins where an individual is in both,
    # because that is the panel f-statistics use.
    merged: dict[str, curate_mod.CuratedSample] = {s.id: s for s in samples_ho}
    merged.update({s.id: s for s in samples_1240k})
    samples = sorted(merged.values(), key=lambda s: (s.group_id, s.id))

    populations, pop_log = curate_mod.build_populations(
        samples,
        data_source=f"AADR-{args.aadr_version}",
        spaces=[PCA_SPACE.space_id] if records_ho else [],
    )
    log.info("populations: %d", len(populations))

    derived = p.derived
    n_pops = write_populations(populations, derived / "populations.parquet")
    n_samples = write_samples(samples, derived / "samples.parquet")
    n_pubs = write_publications(_publication_rows(samples), derived / "publications.parquet")

    exclusions = {
        "1240K": log_1240k.as_dict(),
        "HO": log_ho.as_dict(),
        "populations": pop_log.as_dict(),
    }
    state = {
        "aadr_version": args.aadr_version,
        "counts": {"populations": n_pops, "samples": n_samples, "publications": n_pubs},
        "exclusions": exclusions,
        "panel": {
            "matched_groups": len(resolution.matched),
            "unmatched_labels": sorted(resolution.unmatched),
            "roles": {
                role: sum(1 for r in resolution.roles.values() if r == role)
                for role in sorted(set(resolution.roles.values()))
            },
        },
        "notes": ctx.notes,
    }
    (p.work / "curate.json").parent.mkdir(parents=True, exist_ok=True)
    (p.work / "curate.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(json.dumps(state["counts"], indent=2))
    for note in ctx.notes:
        print(f"note: {note}", file=sys.stderr)
    return 0


def cmd_pca(args: argparse.Namespace) -> int:
    from .pcaspace import build_space

    p = paths(args.root)
    prefix = p.aadr_dir("HO") / DATASETS["HO"].stem
    if not Path(f"{prefix}.geno").is_file():
        print(f"error: {prefix}.geno not found. Run `download` first.", file=sys.stderr)
        return 2

    samples_path = p.derived / "samples.parquet"
    if not samples_path.is_file():
        print("error: run `python -m pipeline curate` first.", file=sys.stderr)
        return 2

    import pandas as pd

    df = pd.read_parquet(samples_path)
    samples = [
        curate_mod.CuratedSample(
            id=r.id,
            population_id=r.population_id,
            group_id=r.group_id,
            master_id=r.master_id,
            sex=r.sex,
            date_mean_bp=r.date_mean_bp,
            date_sd=r.date_sd,
            lat=r.lat,
            lon=r.lon,
            country=r.country,
            locality=r.locality,
            data_type=r.data_type,
            n_snps=r.n_snps,
            pseudohaploid=bool(r.pseudohaploid),
            publication_id=r.publication_id,
            assessment=r.assessment,
            is_present_day=not bool(r.pseudohaploid),
            panel_block=None,
        )
        for r in df.itertuples()
    ]

    build = build_space(prefix=prefix, samples=samples, aadr_version=args.aadr_version)
    coords_path = p.derived / "coordinates" / f"{PCA_SPACE.space_id}.parquet"
    n = write_coordinates(
        sample_ids=build.sample_ids,
        population_ids=build.population_ids,
        coords=build.coords,
        dim_names=build.space["dim_names"],
        n_snps_used=build.n_snps_used,
        projected=build.projected,
        path=coords_path,
    )
    write_spaces([build.space], p.derived / "spaces.json")
    model_path = p.derived / "pca" / f"{PCA_SPACE.space_id}.npz"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    build.model.save(model_path)

    # The SNP panel user uploads are harmonised onto, in the model's SNP order
    # so loadings and panel rows line up. `ref` is the counted allele
    # (EIGENSTRAT .snp column 5), which is the dosage harmonize() returns.
    from strata.io import write_panel_parquet

    write_panel_parquet(build.panel, p.derived / "snp_panel.parquet")

    (p.work / "pca.json").write_text(json.dumps(build.space, indent=2), encoding="utf-8")
    print(json.dumps({"coordinates_rows": n, "space": build.space["id"]}, indent=2))
    return 0


def _as_list(value: Any) -> list[Any]:
    """A parquet list cell as a Python list (pyarrow gives numpy arrays or None)."""
    if value is None:
        return []
    return list(value)


def cmd_f2(args: argparse.Namespace) -> int:
    from .f2stage import build_f2

    p = paths(args.root)
    prefix = p.aadr_dir("1240K") / DATASETS["1240K"].stem
    if not Path(f"{prefix}.geno").is_file():
        print(f"error: {prefix}.geno not found. Run `download` first.", file=sys.stderr)
        return 2

    import pandas as pd

    pops_path = p.derived / "populations.parquet"
    samples_path = p.derived / "samples.parquet"
    if not pops_path.is_file() or not samples_path.is_file():
        print("error: run `python -m pipeline curate` first.", file=sys.stderr)
        return 2

    pdf = pd.read_parquet(pops_path)
    sdf = pd.read_parquet(samples_path)
    populations = [
        curate_mod.CuratedPopulation(
            id=r.id,
            group_id=r.group_id,
            name=r.name,
            region=r.region,
            country=r.country,
            lat=r.lat,
            lon=r.lon,
            period=r.period,
            culture=r.culture,
            date_mean_bp=r.date_mean_bp,
            date_sd=r.date_sd,
            date_min_bp=r.date_min_bp,
            date_max_bp=r.date_max_bp,
            n_samples=int(r.n_samples),
            data_source=r.data_source,
            publication_ids=_as_list(r.publication_ids),
            spaces=_as_list(r.spaces),
            role=r.role,
            panel_block=r.panel_block,
        )
        for r in pdf.itertuples()
    ]
    samples = [
        curate_mod.CuratedSample(
            id=r.id,
            population_id=r.population_id,
            group_id=r.group_id,
            master_id=r.master_id,
            sex=r.sex,
            date_mean_bp=r.date_mean_bp,
            date_sd=r.date_sd,
            lat=r.lat,
            lon=r.lon,
            country=r.country,
            locality=r.locality,
            data_type=r.data_type,
            n_snps=r.n_snps,
            pseudohaploid=bool(r.pseudohaploid),
            publication_id=r.publication_id,
            assessment=r.assessment,
            is_present_day=not bool(r.pseudohaploid),
        )
        for r in sdf.itertuples()
    ]
    eligible = curate_mod.f2_eligible(populations)

    try:
        build = build_f2(
            prefix=prefix,
            out_dir=p.f2_dir(args.reference_version),
            populations=eligible,
            samples=samples,
            overwrite=args.force,
            timeout=args.timeout,
            work_dir=p.work / "f2-input",
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = {
        "f2_dir": str(build.f2_dir),
        "n_pops": build.n_pops,
        "n_snps": build.n_snps,
        "n_blocks": build.n_blocks,
        "cache_id": build.cache_id,
        "options": build.options,
    }
    (p.work / "f2.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    p = paths(args.root)
    derived = p.derived
    if not (derived / "populations.parquet").is_file():
        print("error: nothing to describe; run `curate` first.", file=sys.stderr)
        return 2

    def _load(name: str) -> dict[str, Any]:
        path = p.work / name
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    curate_state = _load("curate.json")
    pca_state = _load("pca.json")
    f2_state = _load("f2.json")
    download_state = _load(f"../raw/aadr/{args.aadr_version}/download.json")

    sources: list[dict[str, Any]] = []
    for key, info in (download_state or {}).items():
        for filename, digest in (info.get("files") or {}).items():
            sources.append(
                {
                    "name": f"AADR {args.aadr_version} {key}: {filename}",
                    "doi": AADR_DOI,
                    "url": (
                        "https://dataverse.harvard.edu/dataset.xhtml?persistentId="
                        f"doi:{AADR_DOI}"
                    ),
                    "sha256": digest,
                }
            )
    if not sources:
        sources.append(
            {
                "name": f"AADR {args.aadr_version}",
                "doi": AADR_DOI,
                "note": (
                    "download.json absent: source checksums were not recorded by this "
                    "run. Rerun `python -m pipeline download` to populate them."
                ),
            }
        )

    man = manifest_mod.build_manifest(
        root=derived,
        version=args.reference_version,
        aadr_version=args.aadr_version,
        sources=sources,
        counts=curate_state.get("counts", {}),
        qc={
            "min_snps": QC.min_snps,
            "allowed_assessments": list(QC.allowed_assessments),
            "reject_assessment_substrings": list(QC.reject_assessment_substrings),
            "reject_group_substrings": list(QC.reject_group_substrings),
            "deduplicate_on_master_id": QC.deduplicate_on_master_id,
            "min_population_size": QC.min_population_size,
        },
        exclusions=curate_state.get("exclusions", {}),
        spaces=[pca_state] if pca_state else [],
        f2={
            **f2_state,
            "config": {
                "blgsize": F2.blgsize,
                "maxmiss": F2.maxmiss,
                "auto_only": F2.auto_only,
                "adjust_pseudohaploid": F2.adjust_pseudohaploid,
                "min_snps_for_f2": F2.min_snps_for_f2,
            },
        },
        panel=curate_state.get("panel", {}),
        notes=curate_state.get("notes", []),
    )
    path = manifest_mod.write_manifest(man, derived)
    written = json.loads(path.read_text(encoding="utf-8"))
    print(f"wrote {path} describing {len(written['artefacts'])} artefact(s)")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    p = paths(args.root)
    try:
        report = manifest_mod.verify_manifest(p.derived)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {k: (len(v) if k == "ok" else v) for k, v in report.items()},
            indent=2,
        )
    )
    return 1 if report["changed"] or report["missing"] else 0


def cmd_citations(_args: argparse.Namespace) -> int:
    for c in AADR_CITATIONS:
        print(f"- {c}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    for stage in (cmd_download, cmd_curate, cmd_pca, cmd_f2, cmd_manifest):
        code = stage(args)
        if code != 0:
            print(f"stage {stage.__name__} failed with code {code}", file=sys.stderr)
            return code
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline",
        description="Build Strata's AADR-derived reference library.",
    )
    ap.add_argument("--root", type=Path, default=None, help="monorepo root (default: autodetect)")
    ap.add_argument("--aadr-version", default=AADR_VERSION)
    ap.add_argument("--reference-version", default=REFERENCE_VERSION)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("inspect-anno", help="resolve a .anno header without building")
    s.add_argument("path", type=Path)
    s.set_defaults(func=cmd_inspect_anno)

    s = sub.add_parser("download", help="fetch AADR datasets from Harvard Dataverse")
    s.add_argument("--datasets", nargs="*", choices=sorted(DATASETS), default=None)
    s.add_argument("--refresh-listing", action="store_true")
    s.set_defaults(func=cmd_download)

    s = sub.add_parser("curate", help="parse .anno, apply QC, write parquet")
    s.add_argument(
        "--all-groups",
        action="store_true",
        help="keep every AADR group, not just the curated panel",
    )
    s.set_defaults(func=cmd_curate)

    s = sub.add_parser("pca", help="fit strata-pca-v1 and project individuals")
    s.set_defaults(func=cmd_pca)

    s = sub.add_parser("f2", help="build the ADMIXTOOLS 2 f2 block cache")
    s.add_argument("--force", action="store_true", help="overwrite an existing cache")
    s.add_argument("--timeout", type=float, default=None)
    s.set_defaults(func=cmd_f2)

    s = sub.add_parser("manifest", help="hash artefacts and write MANIFEST.json")
    s.set_defaults(func=cmd_manifest)

    s = sub.add_parser("verify", help="re-hash artefacts against MANIFEST.json")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("citations", help="print the citations using this data requires")
    s.set_defaults(func=cmd_citations)

    s = sub.add_parser("all", help="download, curate, pca, f2, manifest")
    s.add_argument("--datasets", nargs="*", choices=sorted(DATASETS), default=None)
    s.add_argument("--refresh-listing", action="store_true")
    s.add_argument("--all-groups", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument("--timeout", type=float, default=None)
    s.set_defaults(func=cmd_all)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
