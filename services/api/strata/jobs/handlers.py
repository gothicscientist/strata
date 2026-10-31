"""Built-in job handlers. Each one resolves inputs (decrypting user datasets in memory), calls
the science functions (strata.analysis / strata.qpadm), and records results with provenance.

Payloads are either ``{"analysis_id": ...}`` (an Analysis row created by the API: params come
from the row and the result is stored on it) or ``{"params": {...}}`` (ad-hoc jobs from the
research agent: the result is stored on the job only).

Analysis params (all kinds accept ``seed``):

* pca_project      - dataset_id (raw DNA / VCF: projected into ``space``, default the
                     reference PCA space; G25: rows returned as-is in the g25 space).
* nearest          - target, space, k=10, metric="euclidean", exclude=[].
* admixture_fit    - target, sources=[...] and/or source_dataset_id, method="qp",
                     n_bootstrap=200 (0 disables), sensitivity=True.
* admixture_rotate - target, candidates=[...] and/or source_dataset_id, k_min=1, k_max=3,
                     max_models=20000, min_weight=0.01, top_n=25.
* qpadm            - target, left (or sources), right, f2_dir (default: reference cache).
* qpadm_rotate     - target, candidates (leftright), right (rightfix), min/max_sources.
* f4               - pop1..pop4 lists.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import numpy as np

from strata.api import science
from strata.api.datasets import DatasetPayload, decode_payload
from strata.db.models import Analysis, Dataset
from strata.db.types import utcnow
from strata.jobs.queue import PermanentJobError
from strata.jobs.registry import JobContext, register
from strata.reports.provenance import base_provenance

G25 = "g25"


# ------------------------------------------------------------------ helpers


def _unavailable(exc: Exception) -> PermanentJobError:
    return PermanentJobError(str(exc))


# Parameter spellings used by the web composer, mapped to the canonical names per kind.
_ALIASES: dict[str, dict[str, str]] = {
    "*": {"target_population": "target"},
    "admixture_fit": {"bootstrap": "n_bootstrap"},
    "admixture_rotate": {"min_sources": "k_min", "max_sources": "k_max"},
}


def _normalise(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    out = dict(params)
    for alias, canon in {**_ALIASES["*"], **_ALIASES.get(kind, {})}.items():
        if alias in out:
            v = out.pop(alias)
            if out.get(canon) is None and v is not None:
                out[canon] = v
    return out


def _load_params(ctx: JobContext) -> tuple[Analysis | None, dict[str, Any]]:
    analysis, params = _load_raw_params(ctx)
    return analysis, _normalise(ctx.kind, params)


def _load_raw_params(ctx: JobContext) -> tuple[Analysis | None, dict[str, Any]]:
    aid = ctx.payload.get("analysis_id")
    if aid is None:
        return None, dict(ctx.payload.get("params") or {})
    a = ctx.session.get(Analysis, uuid.UUID(str(aid)))
    if a is None:
        raise PermanentJobError(f"analysis {aid} no longer exists")
    if a.status == "cancelled":
        from strata.jobs.registry import JobCancelledError

        raise JobCancelledError(str(aid))
    a.status = "running"
    a.job_id = ctx.job_id
    ctx.session.flush()
    return a, dict(a.params or {})


def _open_dataset(ctx: JobContext, dataset_id: Any) -> tuple[Dataset, DatasetPayload]:
    from strata.security.vault import DatasetShreddedError, vault_from_settings

    try:
        did = uuid.UUID(str(dataset_id))
    except ValueError as exc:
        raise PermanentJobError("invalid dataset id") from exc
    ds = ctx.session.get(Dataset, did)
    # Owner check: a job may only read datasets of the user who submitted it.
    if ds is None or ds.owner_id != ctx.owner_id:
        raise PermanentJobError("dataset not found")
    try:
        payload = decode_payload(vault_from_settings().open(ctx.session, ds))
    except DatasetShreddedError as exc:
        raise PermanentJobError("dataset was deleted") from exc
    return ds, payload


def project_dataset(payload: DatasetPayload, space: str) -> dict[str, Any] | None:
    """Project a harmonised raw-DNA payload into a reference PCA space."""
    if payload.format != "dosage-npz-v1":
        if payload.format == "calls-npz-v1":
            raise PermanentJobError(
                "this dataset was uploaded before a reference SNP panel was installed; "
                "re-upload it to harmonise it"
            )
        return None
    from strata.analysis import pca

    try:
        model = science.pca_model(space)
    except science.ScienceUnavailableError as exc:
        raise _unavailable(exc) from exc
    enc = payload.arrays["dosage"]
    dosage = np.where(enc < 0, np.nan, enc.astype(np.float64))
    if dosage.shape[0] != model.n_snps:
        raise PermanentJobError(
            f"dataset was harmonised to a panel of {dosage.shape[0]} SNPs but the PCA model "
            f"uses {model.n_snps}; re-upload the file against the current reference"
        )
    proj = pca.project(dosage, model, names=[payload.meta.get("sample_name", "sample")])
    coords = proj.coordinates[0]
    if not all(np.isfinite(coords)):
        raise PermanentJobError(
            f"too few SNPs overlap the PCA model ({proj.n_snps_used[0]}) to project this sample"
        )
    return {
        "space": proj.space,
        "coords": coords,
        "n_snps_used": proj.n_snps_used[0],
        "explained_variance_ratio": proj.explained_variance_ratio,
        "note": proj.note,
    }


def _resolve_target(
    ctx: JobContext, analysis: Analysis | None, params: dict[str, Any]
) -> tuple[str, np.ndarray, str, dict[str, Any]]:
    """Returns (label, coords, space, info). Target from the user's dataset or a reference
    population id."""
    dataset_ids = list(analysis.dataset_ids) if analysis else []
    did = params.get("dataset_id") or (dataset_ids[0] if dataset_ids else None)
    target = params.get("target")
    info: dict[str, Any] = {}
    if did is not None and str(did) != str(params.get("source_dataset_id")):
        ds, payload = _open_dataset(ctx, did)
        info["dataset"] = {
            "id": str(ds.id),
            "input_sha256": ds.input_sha256,
            "payload_sha256": ds.payload_sha256,
        }
        if payload.format == "g25-json-v1":
            names: list[str] = payload.meta["names"]
            if target is None:
                if len(names) != 1:
                    raise PermanentJobError("dataset has several samples; specify `target`")
                target = names[0]
            if target not in names:
                raise PermanentJobError(f"sample {target!r} not in dataset")
            space = params.get("space") or G25
            if space != G25:
                raise PermanentJobError("G25 coordinates can only be analysed in the g25 space")
            return target, payload.arrays["matrix"][names.index(target)], G25, info
        space = params.get("space") or science.default_pca_space() or "strata-pca-v1"
        proj = project_dataset(payload, space)
        assert proj is not None
        info["projection"] = {k: proj[k] for k in ("n_snps_used", "note")}
        return ds.name, np.asarray(proj["coords"], dtype=float), proj["space"], info
    if not target:
        raise PermanentJobError("specify a dataset or a reference population as `target`")
    space = params.get("space") or science.default_pca_space() or G25
    table = _reference_table(space)
    if target not in table.names:
        raise PermanentJobError(f"population {target!r} has no coordinates in space {space!r}")
    return str(target), table.row(target), space, info


def _reference_table(space: str) -> Any:
    try:
        return science.coordinate_table(space)
    except science.ScienceUnavailableError as exc:
        raise _unavailable(exc) from exc


def _group_sheet(
    names: list[str], matrix: np.ndarray
) -> tuple[list[str], np.ndarray, dict[str, np.ndarray]]:
    """G25 sample sheets name rows "Population:Sample"; average rows per population and keep
    the individuals for bootstrap. Rows without ":" are populations on their own."""
    groups: dict[str, list[int]] = {}
    for i, n in enumerate(names):
        groups.setdefault(n.split(":", 1)[0] if ":" in n else n, []).append(i)
    pops = list(groups)
    means = np.vstack([matrix[groups[p]].mean(axis=0) for p in pops])
    samples = {p: matrix[groups[p]] for p in pops}
    return pops, means, samples


def _source_table(
    ctx: JobContext, params: dict[str, Any], space: str, key: str
) -> tuple[Any, dict[str, np.ndarray], dict[str, Any]]:
    """Sources from a user G25 source sheet and/or reference populations in `space`."""
    from strata.analysis.types import CoordinateTable

    wanted = [str(s) for s in (params.get(key) or [])]
    names: list[str] = []
    rows: list[np.ndarray] = []
    samples: dict[str, np.ndarray] = {}
    info: dict[str, Any] = {}
    sheet_id = params.get("source_dataset_id")
    if sheet_id:
        ds, payload = _open_dataset(ctx, sheet_id)
        if payload.format != "g25-json-v1" or space != G25:
            raise PermanentJobError("source sheets must be G25 coordinate datasets (g25 space)")
        pops, means, smp = _group_sheet(payload.meta["names"], payload.arrays["matrix"])
        use = [p for p in pops if not wanted or p in wanted]
        for p in use:
            names.append(p)
            rows.append(means[pops.index(p)])
            samples[p] = smp[p]
        info["source_dataset"] = {"id": str(ds.id), "input_sha256": ds.input_sha256}
        wanted = [w for w in wanted if w not in pops]
    if wanted:
        table = _reference_table(space)
        missing = [w for w in wanted if w not in table.names]
        if missing:
            raise PermanentJobError(f"unknown sources in space {space!r}: {', '.join(missing)}")
        for w in wanted:
            names.append(w)
            rows.append(table.row(w))
            try:
                ind = science.sample_coordinates(space, w)
            except science.ScienceUnavailableError:
                ind = None
            if ind is not None and len(ind):
                samples[w] = ind
    if not names:
        raise PermanentJobError(f"no sources given (`{key}` or source_dataset_id)")
    if len(set(names)) != len(names):
        raise PermanentJobError("duplicate source names")
    return CoordinateTable(space=space, names=names, matrix=np.vstack(rows)), samples, info


def _finish(
    ctx: JobContext,
    analysis: Analysis | None,
    result: dict[str, Any],
    params: dict[str, Any],
    info: dict[str, Any],
    t0: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prov = base_provenance(params.get("seed"), science.reference_version())
    prov.update(
        {
            "job_id": str(ctx.job_id),
            "attempt": ctx.attempt,
            "started_at": (utcnow()).isoformat(),
            "elapsed_s": round(time.monotonic() - t0, 3),
            "inputs": info,
            **(extra or {}),
        }
    )
    if analysis is not None:
        analysis.result = result
        analysis.provenance = prov
        analysis.status = "succeeded"
        analysis.error = None
        analysis.finished_at = utcnow()
        ctx.session.flush()
        return {"analysis_id": str(analysis.id), "result_kind": result.get("kind")}
    return {"result": result, "provenance": prov}


def _seed(params: dict[str, Any]) -> int:
    s = params.get("seed", 0)
    try:
        return int(s)
    except (TypeError, ValueError) as exc:
        raise PermanentJobError("seed must be an integer") from exc


def _int(params: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    v = params.get(key, default)
    try:
        v = int(v)
    except (TypeError, ValueError) as exc:
        raise PermanentJobError(f"{key} must be an integer") from exc
    if not lo <= v <= hi:
        raise PermanentJobError(f"{key} must be between {lo} and {hi}")
    return v


def _analysis_mod(name: str) -> Any:
    try:
        return science._module(f"strata.analysis.{name}")
    except science.ScienceUnavailableError as exc:
        raise _unavailable(exc) from exc


# ------------------------------------------------------------------ exploratory


@register("pca_project", timeout_s=300, description="Project a user sample into a PCA space")
def pca_project(ctx: JobContext) -> dict[str, Any]:
    t0 = time.monotonic()
    analysis, params = _load_params(ctx)
    from strata.analysis.types import EXPLORATORY_CAVEAT

    label, coords, space, info = _resolve_target(ctx, analysis, params)
    proj = info.get("projection", {})
    result = {
        "type": "pca_project",
        "kind": "exploratory",
        "space": space,
        "targets": [{"name": label, "coords": [float(x) for x in coords]}],
        "n_snps_used": proj.get("n_snps_used"),
        "note": proj.get("note"),
        "caveat": EXPLORATORY_CAVEAT,
    }
    return _finish(ctx, analysis, result, params, info, t0)


@register("nearest", timeout_s=120, description="Nearest reference populations")
def nearest(ctx: JobContext) -> dict[str, Any]:
    t0 = time.monotonic()
    analysis, params = _load_params(ctx)
    dist = _analysis_mod("distance")
    from strata.analysis.types import EXPLORATORY_CAVEAT

    label, coords, space, info = _resolve_target(ctx, analysis, params)
    table = _reference_table(space)
    k = _int(params, "k", 10, 1, 200)
    metric = params.get("metric", "euclidean")
    exclude = [str(x) for x in params.get("exclude", [])]
    if not analysis or not analysis.dataset_ids:
        exclude.append(label)  # a reference population is trivially nearest to itself
    try:
        res = dist.nearest(coords, table, k=k, metric=metric, target_name=label, exclude=exclude)
    except ValueError as exc:
        raise PermanentJobError(str(exc)) from exc
    result = {
        "type": "nearest",
        "kind": "exploratory",
        "space": space,
        "target": label,
        "metric": res.metric,
        "hits": [
            {"population_id": n.name, "name": n.name, "distance": n.distance, "rank": n.rank}
            for n in res.neighbors
        ],
        "caveat": EXPLORATORY_CAVEAT,
    }
    return _finish(ctx, analysis, result, params, info, t0)


@register("admixture_fit", timeout_s=900, description="Exploratory convex mixture fit")
def admixture_fit(ctx: JobContext) -> dict[str, Any]:
    t0 = time.monotonic()
    analysis, params = _load_params(ctx)
    adm = _analysis_mod("admixture")
    label, coords, space, info = _resolve_target(ctx, analysis, params)
    sources, samples, sinfo = _source_table(ctx, params, space, "sources")
    info.update(sinfo)
    method = params.get("method", "qp")
    seed = _seed(params)
    n_boot = _int(params, "n_bootstrap", 200, 0, 5000)
    try:
        fit = adm.fit(coords, sources, method=method, space=space, target_name=label)
        ctx.check()
        boot = None
        if n_boot and all(n in samples and len(samples[n]) >= 2 for n in sources.names):
            boot = adm.bootstrap(
                coords,
                {n: samples[n] for n in sources.names},
                n=n_boot,
                seed=seed,
                method=method,
                space=space,
                target_name=label,
            )
        ctx.check()
        sens = (
            adm.sensitivity(coords, sources, method=method, seed=seed, target_name=label)
            if params.get("sensitivity", True) and len(sources.names) >= 2
            else None
        )
    except ValueError as exc:
        raise PermanentJobError(str(exc)) from exc
    ci = {w.name: w for w in boot.weights} if boot else {}
    notes = []
    if n_boot and boot is None:
        notes.append(
            "Bootstrap skipped: individual-level coordinates are not available for "
            "every source (needs >= 2 individuals each). Weights have no CI."
        )
    result = {
        "type": "admixture_fit",
        "kind": "exploratory",
        "space": space,
        "target": label,
        "method": fit.method,
        "weights": [
            {
                "source": s.name,
                "weight": s.weight,
                "se": ci[s.name].se if s.name in ci else None,
                "ci_low": ci[s.name].ci_low if s.name in ci else None,
                "ci_high": ci[s.name].ci_high if s.name in ci else None,
            }
            for s in fit.sources
        ],
        "distance": fit.distance,
        "residuals": fit.residuals,
        "quality": fit.quality.model_dump(mode="json") if fit.quality else None,
        "converged": fit.converged,
        "n_bootstrap": boot.n_bootstrap if boot else None,
        "bootstrap": boot.model_dump(mode="json", exclude={"point"}) if boot else None,
        "sensitivity": _sensitivity_out(sens) if sens else None,
        "caveat": fit.caveat,
        "notes": notes,
    }
    return _finish(ctx, analysis, result, params, info, t0)


def _sensitivity_out(sens: Any) -> dict[str, Any]:
    def rows(xs: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "dropped": r.dropped,
                "distance": r.distance,
                "delta_distance": r.delta_distance,
                "weights": {w.name: w.weight for w in r.weights},
                "max_abs_weight_change": r.max_abs_weight_change,
            }
            for r in xs
        ]

    return {
        "leave_one_source_out": rows(sens.leave_one_source_out),
        "leave_one_dimension_out": rows(sens.leave_one_dimension_out),
        "jitter": sens.jitter.model_dump(mode="json") if sens.jitter else None,
        "stable": sens.stable,
        "stability_note": sens.stability_note,
    }


@register("admixture_rotate", timeout_s=1800, description="Exploratory source rotation")
def admixture_rotate(ctx: JobContext) -> dict[str, Any]:
    t0 = time.monotonic()
    analysis, params = _load_params(ctx)
    adm = _analysis_mod("admixture")
    label, coords, space, info = _resolve_target(ctx, analysis, params)
    cands, _, sinfo = _source_table(ctx, params, space, "candidates")
    info.update(sinfo)
    k_min = _int(params, "k_min", 1, 1, 8)
    k_max = _int(params, "k_max", 3, k_min, 8)
    try:
        res = adm.rotate(
            coords,
            cands,
            (k_min, k_max),
            max_models=_int(params, "max_models", 20000, 1, 200000),
            seed=_seed(params),
            min_weight=float(params.get("min_weight", 0.01)),
            top_n=_int(params, "top_n", 25, 1, 200),
            method=params.get("method", "qp"),
            target_name=label,
        )
    except ValueError as exc:
        raise PermanentJobError(str(exc)) from exc
    result = {
        "type": "admixture_rotate",
        "kind": "exploratory",
        "space": space,
        "target": label,
        "models": [
            {
                "rank": m.rank,
                "sources": [s.name for s in m.sources],
                "weights": [s.weight for s in m.sources],
                "distance": m.distance,
                "n_sources": m.n_sources,
                "pruned": m.pruned_from,
            }
            for m in res.models
        ],
        "n_models_evaluated": res.n_models_evaluated,
        "n_candidates": res.n_candidates,
        "strategy": res.strategy,
        "preferred_rank": res.preferred_rank,
        "tolerance": res.tolerance,
        "min_weight": res.min_weight,
        "k_range": list(res.k_range),
        "caveat": res.caveat,
    }
    return _finish(ctx, analysis, result, params, info, t0)


# ------------------------------------------------------------------ formal (ADMIXTOOLS 2)


def _qpadm_mod() -> Any:
    try:
        mod = science._module("strata.qpadm")
    except science.ScienceUnavailableError as exc:
        raise _unavailable(exc) from exc
    if not mod.qpadm_available():
        raise PermanentJobError("qpAdm is unavailable on this worker (R + ADMIXTOOLS 2 missing)")
    return mod


def _data_source(mod: Any, params: dict[str, Any]) -> dict[str, Any]:
    if params.get("geno_prefix") or params.get("f2_dir"):
        # Clients may not point R at arbitrary server paths; only the configured cache.
        f2 = mod.default_f2_dir()
        if params.get("f2_dir") and (f2 is None or str(params["f2_dir"]) != str(f2)):
            raise PermanentJobError(
                "custom f2_dir/geno_prefix is not allowed; omit it to use the reference f2 cache"
            )
        if params.get("geno_prefix"):
            raise PermanentJobError("geno_prefix is not accepted from API clients")
    f2 = mod.default_f2_dir()
    if f2 is None:
        raise PermanentJobError(
            "no reference f2 cache is built on this server (see data/pipeline; STRATA_F2_DIR)"
        )
    return {"f2_dir": str(f2)}


_POP_FIELDS = (
    "target",
    "left",
    "right",
    "candidates",
    "leftright",
    "rightfix",
    "pop1",
    "pop2",
    "pop3",
    "pop4",
)


def _to_group_ids(spec_args: dict[str, Any]) -> dict[str, str]:
    """qpAdm labels are AADR group ids (the f2 cache's population names). Map Strata
    population ids to them; names that are not library ids pass through unchanged."""
    lib = science.try_reference_library()
    if lib is None:
        return {}
    pops = {p.id: p for p in lib.populations()}
    mapping: dict[str, str] = {}

    def conv(name: Any) -> Any:
        p = pops.get(str(name))
        gid = getattr(p, "group_id", None) if p is not None else None
        if gid and gid != name:
            mapping[str(name)] = gid
            return gid
        return name

    for k in _POP_FIELDS:
        v = spec_args.get(k)
        if isinstance(v, list):
            spec_args[k] = [conv(x) for x in v]
        elif isinstance(v, str):
            spec_args[k] = conv(v)
    return mapping


def _formal_error(exc: Exception, mod: Any) -> Exception:
    if isinstance(exc, getattr(mod, "QpAdmTimeout", ())):
        return PermanentJobError(f"qpAdm timed out: {exc}")
    if isinstance(exc, getattr(mod, "QpAdmUnavailable", ())):
        return PermanentJobError(f"qpAdm unavailable: {exc}")
    if isinstance(exc, getattr(mod, "QpAdmRunError", ()) | ValueError):
        return PermanentJobError(str(exc))
    return exc


def _weights_out(rows: list[Any]) -> list[dict[str, Any]]:
    return [{"source": w.left, "weight": w.weight, "se": w.se, "z": w.z} for w in rows]


def _feasible(feas: Any, weights: list[Any]) -> bool:
    if feas is not None and feas.weights_in_unit_interval is not None:
        return bool(feas.weights_in_unit_interval)
    return all(0.0 <= w.weight <= 1.0 for w in weights)


_SPEC_DROP = {"target_label", "dataset_id", "source_dataset_id", "space", "seed"}


@register("qpadm", timeout_s=3600, description="Formal qpAdm admixture test (ADMIXTOOLS 2)")
def qpadm(ctx: JobContext) -> dict[str, Any]:
    t0 = time.monotonic()
    analysis, params = _load_params(ctx)
    mod = _qpadm_mod()
    spec_args = {k: v for k, v in params.items() if k not in _SPEC_DROP}
    if "sources" in spec_args and "left" not in spec_args:
        spec_args["left"] = spec_args.pop("sources")
    spec_args.update(_data_source(mod, spec_args))
    group_map = _to_group_ids(spec_args)
    try:
        spec = mod.QpAdmSpec(**spec_args)
        res = mod.run_qpadm(spec)
    except Exception as exc:  # noqa: BLE001 - mapped below
        raise _formal_error(exc, mod) from exc
    feas = res.feasibility
    result = {
        "type": "qpadm",
        "kind": "formal",
        "target": res.target,
        "left": res.left,
        "right": res.right,
        "weights": _weights_out(res.weights),
        "p_value": res.p,
        "chisq": res.chisq,
        "dof": res.dof,
        "feasible": _feasible(feas, res.weights),
        "verdict": feas.verdict if feas else None,
        "rank_tests": [
            {
                "rank": r.f4rank,
                "dof": r.dof,
                "chisq": r.chisq,
                "p": r.p,
                "dofdiff": r.dofdiff,
                "chisqdiff": r.chisqdiff,
                "p_nested": r.p_nested,
            }
            for r in res.rankdrop
        ],
        "f4": [f.model_dump(mode="json") for f in res.f4],
        "notes": list(feas.reasons) if feas else [],
        "caveat": res.caveat,
        "detail": res.model_dump(mode="json", exclude={"provenance"}),
    }
    return _finish(
        ctx,
        analysis,
        result,
        params,
        {"f2_dir": spec_args["f2_dir"], "group_ids": group_map},
        t0,
        {"r": res.provenance.model_dump(mode="json")},
    )


@register("qpadm_rotate", timeout_s=7200, description="Formal qpAdm model rotation")
def qpadm_rotate(ctx: JobContext) -> dict[str, Any]:
    t0 = time.monotonic()
    analysis, params = _load_params(ctx)
    mod = _qpadm_mod()
    spec_args = {k: v for k, v in params.items() if k not in _SPEC_DROP | {"rotate_right"}}
    spec_args.update(_data_source(mod, spec_args))
    group_map = _to_group_ids(spec_args)
    try:
        spec = mod.QpAdmRotateSpec(**spec_args)
        res = mod.run_qpadm_rotate(spec)
    except Exception as exc:  # noqa: BLE001
        raise _formal_error(exc, mod) from exc
    result = {
        "type": "qpadm_rotate",
        "kind": "formal",
        "target": res.target,
        "right": res.rightfix,
        "leftright": res.leftright,
        "models": [
            {
                "left": m.left,
                "right": m.right,
                "p_value": m.p,
                "chisq": m.chisq,
                "dof": m.dof,
                "feasible": _feasible(m.feasibility, m.weights),
                "verdict": m.feasibility.verdict if m.feasibility else None,
                "weights": _weights_out(m.weights),
            }
            for m in res.models
        ],
        "n_models_enumerated": res.n_models_enumerated,
        "n_models_tested": res.n_models_tested,
        "caveat": res.caveat,
        "rotation_caveat": res.rotation_caveat,
    }
    return _finish(
        ctx,
        analysis,
        result,
        params,
        {"f2_dir": spec_args["f2_dir"], "group_ids": group_map},
        t0,
        {"r": res.provenance.model_dump(mode="json")},
    )


@register("f4", timeout_s=1800, description="Formal f4-statistics (ADMIXTOOLS 2)")
def f4(ctx: JobContext) -> dict[str, Any]:
    t0 = time.monotonic()
    analysis, params = _load_params(ctx)
    mod = _qpadm_mod()
    spec_args = {k: v for k, v in params.items() if k not in _SPEC_DROP}
    spec_args.update(_data_source(mod, spec_args))
    group_map = _to_group_ids(spec_args)
    try:
        res = mod.run_f4(mod.F4Spec(**spec_args))
    except Exception as exc:  # noqa: BLE001
        raise _formal_error(exc, mod) from exc
    result = {"type": "f4", **res.model_dump(mode="json", exclude={"provenance"})}
    result["kind"] = "formal"
    return _finish(
        ctx,
        analysis,
        result,
        params,
        {"f2_dir": spec_args["f2_dir"], "group_ids": group_map},
        t0,
        {"r": res.provenance.model_dump(mode="json")},
    )


# ------------------------------------------------------------------ reports


@register("report", timeout_s=120, description="Render a reproducible report bundle")
def report(ctx: JobContext) -> dict[str, Any]:
    from strata.reports import build_bundle, render_html

    aid = ctx.payload.get("analysis_id")
    a = ctx.session.get(Analysis, uuid.UUID(str(aid))) if aid else None
    if a is None or a.owner_id != ctx.owner_id:
        raise PermanentJobError("analysis not found")
    if a.status != "succeeded":
        raise PermanentJobError(f"analysis is {a.status}")
    datasets = [
        d
        for d in (ctx.session.get(Dataset, uuid.UUID(str(i))) for i in a.dataset_ids)
        if d is not None
    ]
    bundle = build_bundle(a, datasets, generated_at=utcnow())
    out: dict[str, Any] = {"analysis_id": str(a.id), "bundle": bundle}
    if ctx.payload.get("format", "json") == "html":
        out["html"] = render_html(bundle)
    return out
