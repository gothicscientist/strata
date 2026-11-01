"""Tools available to the research agent.

Each tool has a JSON schema (sent to the LLM) and an async implementation taking validated
arguments plus a ``ToolContext``. Implementations never raise into the loop: failures are
returned as ``ToolOutcome(ok=False, error=...)`` and shown to the model as tool errors.

Analysis results are stored in a per-run ``ResultStore`` under a ``result_id`` so later tools
(``compare_models``) operate on actual tool outputs rather than numbers restated by the model.
The agent never receives raw genotypes: only population IDs, derived coordinates and QC
summaries pass through these tools.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import json
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import jsonschema
import numpy as np

from strata.agent.events import ToolSpec
from strata.agent.rag import KnowledgeBase, default_knowledge_base

EXPLORATORY_CAVEAT = (
    "Exploratory coordinate-space fit (G25/PCA). Weights describe a best-fitting mixture of "
    "population means in a low-dimensional summary space; they are not a formal test of "
    "admixture and can fit well for historically wrong models. Confirm with qpAdm."
)

# ---- context and backends --------------------------------------------------------------------


class ReferenceBackend(Protocol):
    """What the tools need from the reference library (``strata.reference``).

    An implementation may also provide
    ``population_samples(space, population_ids) -> dict[str, ndarray]`` (per-individual
    coordinates). It is optional: without it, bootstrap confidence intervals are reported as
    unavailable rather than replaced by a point estimate.

    ``panel() -> dict`` (the curated panel's composition and limits) is optional in the same
    way: without it, ``describe_reference_panel`` says the panel is not described rather than
    describing an empty one, which would read as a panel with no limits.
    """

    def search(
        self, query: str | None, region: str | None, period: str | None, limit: int
    ) -> list[dict[str, Any]]: ...

    def get(self, population_id: str) -> dict[str, Any] | None: ...

    def coordinates(self, space: str) -> tuple[list[str], np.ndarray]: ...

    def all_metadata(self) -> list[dict[str, Any]]: ...


JobRunner = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass
class ToolContext:
    """Everything a tool needs from the platform; constructed per chat request.

    * ``user_id``: owner of the session; dataset access is scoped to it.
    * ``db``: SQLAlchemy session (or None), passed through to platform callables.
    * ``run_job``: ``(job_kind, payload) -> result dict`` (sync or async). Used for qpAdm jobs
      so they run on the worker; when absent, tools call ``strata.qpadm`` in-process.
    * ``list_datasets``: ``user_id -> [{id, kind, name, created_at, qc}]``.
    * ``get_dataset_coordinates``: ``(dataset_id, space) -> {"space","name","coords"}`` with
      derived coordinates only; returns None if not available in that space.
    * ``reference``: override of the reference backend (tests, alternative libraries).
    * ``knowledge``: override of the RAG knowledge base.
    """

    user_id: str
    db: Any = None
    run_job: JobRunner | None = None
    list_datasets: Callable[[str], list[dict[str, Any]]] | None = None
    get_dataset_coordinates: Callable[[str, str], dict[str, Any] | None] | None = None
    reference: ReferenceBackend | None = None
    knowledge: KnowledgeBase | None = None
    default_space: str = "g25"
    results: ResultStore = field(default_factory=lambda: ResultStore())


class ResultStore:
    """Per-run store of analysis results addressable by ``result_id``."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._counter = itertools.count(1)

    def put(self, tool: str, result: dict[str, Any]) -> str:
        rid = f"r{next(self._counter)}"
        self._items[rid] = {"tool": tool, "result": result}
        return rid

    def get(self, rid: str) -> dict[str, Any] | None:
        return self._items.get(rid)


class ToolUnavailableError(Exception):
    """A dependency (module, data, platform hook) is not available in this deployment."""


class ToolInputError(Exception):
    """Arguments are valid JSON but semantically wrong (unknown population, etc.)."""


def _reference(ctx: ToolContext) -> ReferenceBackend:
    if ctx.reference is not None:
        return ctx.reference
    try:
        from strata.agent import backends
    except ImportError as exc:  # pragma: no cover
        raise ToolUnavailableError(f"reference adapter missing: {exc}") from exc
    return backends.default_reference()


def _knowledge(ctx: ToolContext) -> KnowledgeBase:
    if ctx.knowledge is not None:
        return ctx.knowledge
    meta: list[dict[str, Any]] | None = None
    try:
        meta = _reference(ctx).all_metadata()
    except Exception:  # noqa: BLE001 - corpus still works without library metadata
        meta = None
    return default_knowledge_base(meta)


async def _call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a sync library function off the event loop, or await an async one."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    res = await asyncio.to_thread(fn, *args, **kwargs)
    if inspect.isawaitable(res):
        return await res
    return res


def _jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


# ---- target resolution -----------------------------------------------------------------------

TARGET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Either a user dataset (by id) or a reference population (by id).",
    "properties": {
        "dataset_id": {"type": "string"},
        "population": {"type": "string"},
    },
    "additionalProperties": False,
}


@dataclass
class Target:
    label: str
    coords: np.ndarray
    space: str
    dataset_id: str | None = None
    population: str | None = None


async def _resolve_target(ctx: ToolContext, target: dict[str, Any], space: str) -> Target:
    ref = _reference(ctx)
    if target.get("dataset_id"):
        if ctx.get_dataset_coordinates is None:
            raise ToolUnavailableError("dataset coordinates are not available in this deployment")
        did = str(target["dataset_id"])
        data = await _call(ctx.get_dataset_coordinates, did, space)
        if not data or not data.get("coords"):
            raise ToolInputError(f"dataset {did!r} has no coordinates in space {space!r}")
        return Target(
            label=str(data.get("name") or did),
            coords=np.asarray(data["coords"], dtype=float),
            space=space,
            dataset_id=did,
        )
    if target.get("population"):
        pid = str(target["population"])
        names, mat = await _call(ref.coordinates, space)
        if pid not in names:
            raise ToolInputError(f"population {pid!r} has no coordinates in space {space!r}")
        return Target(label=pid, coords=mat[names.index(pid)], space=space, population=pid)
    raise ToolInputError("target must specify dataset_id or population")


async def _source_matrix(
    ctx: ToolContext, sources: list[str], space: str
) -> tuple[list[str], np.ndarray]:
    names, mat = await _call(_reference(ctx).coordinates, space)
    idx = {n: i for i, n in enumerate(names)}
    missing = [s for s in sources if s not in idx]
    if missing:
        raise ToolInputError(f"unknown populations in space {space!r}: {', '.join(missing)}")
    return sources, mat[[idx[s] for s in sources]]


def _coordinate_table(space: str, names: list[str], mat: np.ndarray) -> Any:
    """Build ``strata.analysis.types.CoordinateTable`` (the science core's input type)."""
    try:
        from strata.analysis.types import CoordinateTable
    except ImportError as exc:
        raise ToolUnavailableError(f"strata.analysis.types is not available: {exc}") from exc
    return CoordinateTable(space=space, names=list(names), matrix=np.asarray(mat, dtype=float))


def _analysis(module: str) -> Any:
    import importlib

    try:
        return importlib.import_module(f"strata.analysis.{module}")
    except ImportError as exc:
        raise ToolUnavailableError(f"strata.analysis.{module} is not available: {exc}") from exc


def _qpadm(*, require_local: bool = True) -> Any:
    """Import ``strata.qpadm``.

    ``require_local`` checks that R and ADMIXTOOLS 2 are installed here; it is skipped when a
    job runner will execute the analysis on the worker instead of in this process.
    """
    import importlib

    try:
        mod = importlib.import_module("strata.qpadm")
    except ImportError as exc:
        raise ToolUnavailableError(f"strata.qpadm is not available: {exc}") from exc
    avail = getattr(mod, "qpadm_available", None)
    if require_local and callable(avail) and not avail():
        raise ToolUnavailableError(
            "formal f-statistic analysis is unavailable in this deployment (R with "
            "ADMIXTOOLS 2 is not installed); only exploratory coordinate analyses can run"
        )
    return mod


def _mark_exploratory(result: dict[str, Any], space: str) -> dict[str, Any]:
    result.setdefault("kind", "exploratory")
    result["kind"] = "exploratory"
    result.setdefault("space", space)
    result.setdefault("caveat", EXPLORATORY_CAVEAT)
    return result


# ---- tool implementations --------------------------------------------------------------------


async def search_populations(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    ref = _reference(ctx)
    rows = await _call(
        ref.search,
        args.get("query"),
        args.get("region"),
        args.get("period"),
        int(args.get("limit", 20)),
    )
    out: dict[str, Any] = {"count": len(rows), "populations": _jsonable(rows)}
    # Formal tools read the f2 cache, which carries fewer populations than the
    # coordinate library; say which ones, so a qpAdm model is built from
    # populations it can run on rather than discovered to be missing.
    in_f2 = _f2_population_names()
    if in_f2 is not None:
        for row in out["populations"]:
            if isinstance(row, dict) and row.get("group_id"):
                row["in_f2_cache"] = row["group_id"] in in_f2
    if not rows and (args.get("region") or args.get("period")):
        # Region and period are exact-match filters over this library's own
        # vocabulary, which a model cannot guess; hand it the vocabulary.
        facets = getattr(ref, "facets", None)
        if callable(facets):
            out["accepted_filters"] = await _call(facets)
            out["hint"] = (
                "region and period must match one of accepted_filters exactly; "
                "retry with one of them, or with the query alone"
            )
    return out


def _f2_population_names() -> frozenset[str] | None:
    try:
        from strata.qpadm import default_f2_dir, f2_populations
    except Exception:  # science stack absent: nothing to annotate
        return None
    return f2_populations(default_f2_dir())


async def get_population(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    pid = args["population_id"]
    row = await _call(_reference(ctx).get, pid)
    if row is None:
        raise ToolInputError(f"population {pid!r} not found; use search_populations")
    return {"population": _jsonable(row)}


async def describe_reference_panel(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """The curated panel's composition and its limits.

    Exists so the model starts a right set from the panel's own standing
    outgroup set instead of choosing outgroups itself, and so it knows what
    the panel cannot answer before it builds a model rather than after.
    """
    ref = _reference(ctx)
    describe = getattr(ref, "panel", None)
    if describe is None:
        raise ToolUnavailableError(
            "this deployment's reference adapter does not describe the panel; "
            "supply a right set explicitly"
        )
    panel = await _call(describe)
    if not panel:
        raise ToolUnavailableError(
            "the reference manifest does not record the panel's composition "
            "(it predates panel reporting); supply a right set explicitly"
        )
    limits = list(panel.get("limits") or [])
    right_set = list(panel.get("right_set") or [])
    # The panel records the outgroup set as it resolved in the release; the
    # f2 cache was built from a subset. Offer only what a formal tool can use,
    # and name the rest so the model does not go looking for them.
    in_f2 = _f2_population_names()
    not_in_f2 = [p for p in right_set if in_f2 is not None and p not in in_f2]
    out_right = [p for p in right_set if p not in not_in_f2]
    return {
        "right_set": out_right,
        **({"right_set_not_in_f2_cache": not_in_f2} if not_in_f2 else {}),
        "limits": limits,
        "matched_groups": panel.get("matched_groups"),
        "roles": panel.get("roles") or {},
        # Labels the release does not carry, with the reason. Useful because a
        # population named in the literature may simply not be here, and the
        # model should say so rather than substitute something else silently.
        "unavailable_labels": panel.get("unavailable_labels") or {},
        "guidance": (
            "Use right_set as the starting point for a qpAdm right set; it is the standing "
            "deep-outgroup set for this panel. Each entry in limits is a question this panel "
            "cannot answer: say so in the answer rather than reporting the numbers alone."
        )
        if limits
        else (
            "Use right_set as the starting point for a qpAdm right set; it is the standing "
            "deep-outgroup set for this panel."
        ),
    }


async def list_user_datasets(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if ctx.list_datasets is None:
        raise ToolUnavailableError("dataset listing is not available in this context")
    rows = await _call(ctx.list_datasets, ctx.user_id)
    # Only identifiers and QC summary leave this function - never genotype content.
    allowed = {"id", "kind", "name", "created_at", "qc", "spaces", "vendor", "build"}
    clean = [{k: v for k, v in r.items() if k in allowed} for r in rows]
    return {"count": len(clean), "datasets": _jsonable(clean)}


def _euclidean_nearest(
    target: np.ndarray, names: list[str], mat: np.ndarray, k: int
) -> list[dict[str, Any]]:
    d = np.sqrt(((mat - target[None, :]) ** 2).sum(axis=1))
    order = np.argsort(d, kind="stable")[:k]
    return [{"population": names[i], "distance": float(d[i])} for i in order]


async def nearest_populations(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    space = args.get("space") or ctx.default_space
    k = int(args.get("k", 15))
    tgt = await _resolve_target(ctx, args["target"], space)
    names, mat = await _call(_reference(ctx).coordinates, space)
    dist = _analysis("distance")
    table = _coordinate_table(space, names, mat)
    res = await _call(
        dist.nearest,
        tgt.coords,
        table,
        k,
        "euclidean",
        target_name=tgt.label,
        exclude=[tgt.population] if tgt.population else None,
    )
    out = _jsonable(res)
    out["k"] = k
    return _mark_exploratory(out, space)


async def _sample_coordinates(
    ctx: ToolContext, populations: list[str], space: str
) -> dict[str, np.ndarray]:
    ref = _reference(ctx)
    fn = getattr(ref, "population_samples", None)
    if not callable(fn):
        raise ToolUnavailableError(
            "the reference library does not expose per-sample coordinates, so bootstrap "
            "confidence intervals cannot be computed; run without bootstrap"
        )
    samples = await _call(fn, space, populations)
    out: dict[str, np.ndarray] = {}
    for name in populations:
        arr = samples.get(name) if isinstance(samples, dict) else None
        if arr is None or len(arr) == 0:
            raise ToolUnavailableError(f"no individual-level coordinates for {name!r}")
        out[name] = np.asarray(arr, dtype=float)
    return out


async def fit_admixture(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    space = args.get("space") or ctx.default_space
    tgt = await _resolve_target(ctx, args["target"], space)
    src_names, src = await _source_matrix(ctx, list(args["sources"]), space)
    adm = _analysis("admixture")
    table = _coordinate_table(space, src_names, src)
    fit = await _call(
        adm.fit,
        tgt.coords,
        table,
        method=args.get("method", "qp"),
        space=space,
        target_name=tgt.label,
    )
    out: dict[str, Any] = {"target": tgt.label, "fit": _jsonable(fit)}
    if args.get("bootstrap"):
        samples = await _sample_coordinates(ctx, src_names, space)
        boot = await _call(
            adm.bootstrap,
            tgt.coords,
            samples,
            int(args.get("n_bootstrap", 200)),
            int(args.get("seed", 0)),
            method=args.get("method", "qp"),
            space=space,
            target_name=tgt.label,
        )
        out["bootstrap"] = _jsonable(boot)
    return _mark_exploratory(out, space)


async def rotate_sources(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    space = args.get("space") or ctx.default_space
    tgt = await _resolve_target(ctx, args["target"], space)
    cand_names, cand = await _source_matrix(ctx, list(args["candidates"]), space)
    adm = _analysis("admixture")
    k_min, k_max = int(args.get("k_min", 1)), int(args.get("k_max", 3))
    if k_max < k_min:
        raise ToolInputError("k_max must be >= k_min")
    if k_max > len(cand_names):
        raise ToolInputError("k_max cannot exceed the number of candidates")
    res = await _call(
        adm.rotate,
        tgt.coords,
        _coordinate_table(space, cand_names, cand),
        (k_min, k_max),
        int(args.get("max_models", 2000)),
        int(args.get("seed", 0)),
        target_name=tgt.label,
    )
    return _mark_exploratory({"target": tgt.label, "rotation": _jsonable(res)}, space)


async def sensitivity_analysis(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    space = args.get("space") or ctx.default_space
    tgt = await _resolve_target(ctx, args["target"], space)
    src_names, src = await _source_matrix(ctx, list(args["sources"]), space)
    adm = _analysis("admixture")
    res = await _call(
        adm.sensitivity,
        tgt.coords,
        _coordinate_table(space, src_names, src),
        method=args.get("method", "qp"),
        seed=int(args.get("seed", 0)),
        target_name=tgt.label,
    )
    return _mark_exploratory({"target": tgt.label, "sensitivity": _jsonable(res)}, space)


# Formal (f-statistic) tools. The f2 cache path is resolved server-side: it is never a tool
# parameter, because a different cache means a different SNP set and different p-values.

_SPEC_FOR: dict[str, tuple[str, str]] = {
    "qpadm": ("QpAdmSpec", "run_qpadm"),
    "qpadm_rotate": ("QpAdmRotateSpec", "run_qpadm_rotate"),
    "f4": ("F4Spec", "run_f4"),
}


def _formal_data_source(mod: Any) -> dict[str, str]:
    f2_dir = mod.default_f2_dir()
    if f2_dir is None:
        raise ToolUnavailableError(
            "no reference f2 cache has been built in this deployment, so formal f-statistic "
            "tests cannot run; only exploratory coordinate analyses are available"
        )
    return {"f2_dir": str(f2_dir)}


def _panel_limits(kind: str) -> list[dict[str, Any]]:
    """Panel limits that apply to this tool, as the reference library reports them.

    A limit names the analyses it affects; one that names none is taken to
    affect all of them, so a limit added later cannot be dropped by forgetting
    to list a tool.
    """
    try:
        from strata.api import science

        limits = science.reference_limits()
    except Exception:  # noqa: BLE001 - never fail a computed result over its caveat
        return []
    out = []
    for limit in limits:
        affects = limit.get("affects")
        if not affects or kind in affects:
            out.append({k: limit[k] for k in ("id", "summary") if k in limit})
    return out


async def _run_formal(kind: str, payload: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    mod = _qpadm(require_local=ctx.run_job is None)
    spec_name, fn_name = _SPEC_FOR[kind]
    spec_cls = getattr(mod, spec_name)
    full = {**payload, **_formal_data_source(mod)}
    try:
        spec = spec_cls.model_validate(full)
    except Exception as exc:  # pydantic ValidationError and model validators
        raise ToolInputError(f"invalid {kind} specification: {exc}") from exc
    # Checked here as well as in the runner: on the queue path the runner's
    # error comes back from the worker as a failed job, which the model cannot
    # tell from a broken backend.
    check = getattr(mod, "check_f2_coverage", None)
    if callable(check):
        try:
            check(spec)
        except Exception as exc:
            missing = getattr(exc, "missing", None)
            if missing is None:
                raise
            raise ToolInputError(
                f"{exc} Use search_populations and pick populations with in_f2_cache: true."
            ) from exc
    try:
        if ctx.run_job is not None:
            # Long-running: hand the validated spec to the worker.
            res = await _call(ctx.run_job, kind, spec.model_dump(mode="json"))
        else:
            res = await _call(getattr(mod, fn_name), spec)
    except Exception as exc:
        qpadm_error = getattr(mod, "QpAdmError", ())
        unavailable = getattr(mod, "QpAdmUnavailable", ())
        if unavailable and isinstance(exc, unavailable):
            raise ToolUnavailableError(str(exc)) from exc
        if qpadm_error and isinstance(exc, qpadm_error):
            raise ToolInputError(getattr(exc, "message", None) or str(exc)) from exc
        raise
    out = _jsonable(res)
    if not isinstance(out, dict):
        out = {"result": out}
    out["kind"] = "formal"
    feas = out.get("feasibility")
    if isinstance(feas, dict) and feas.get("reasons"):
        out["interpretation"] = feas["reasons"]
    # A limit of the panel travels with every formal result, because the model
    # cannot see it in the numbers: an under-identified weight looks like any
    # other weight, and a rejected fit looks like a rejected model. Attached
    # here, at the one place every formal tool goes through, so no tool can be
    # added that quietly omits it.
    limits = _panel_limits(kind)
    if limits:
        out["panel_limits"] = limits
    if kind == "qpadm_rotate":
        summarize = getattr(mod, "summarize_rotation", None)
        models = getattr(res, "models", None)
        if callable(summarize) and models:
            out["rotation_summary"] = summarize(models)
    return out


async def run_qpadm(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    left, right = list(args["sources"]), list(args["right"])
    if len(right) <= len(left):
        raise ToolInputError(
            f"qpAdm needs strictly more right than left populations (got {len(left)} left, "
            f"{len(right)} right); add more right populations"
        )
    payload = {"target": args["target"], "left": left, "right": right}
    if "allsnps" in args:
        payload["allsnps"] = args["allsnps"]
    return await _run_formal("qpadm", payload, ctx)


async def run_qpadm_rotate(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    payload = {
        "target": args["target"],
        "leftright": list(args["candidates"]),
        "rightfix": list(args.get("right", [])),
        "max_sources": int(args.get("max_sources", 2)),
        "max_models": int(args.get("max_models", 400)),
    }
    return await _run_formal("qpadm_rotate", payload, ctx)


async def run_f4(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    quads = [list(q) for q in args["quadruples"]]
    if any(len(q) != 4 for q in quads):
        raise ToolInputError("each quadruple must have exactly four populations")
    # comb=False zips the four vectors row-wise, so each quadruple is computed as given.
    payload = {
        "pop1": [q[0] for q in quads],
        "pop2": [q[1] for q in quads],
        "pop3": [q[2] for q in quads],
        "pop4": [q[3] for q in quads],
        "comb": False,
    }
    return await _run_formal("f4", payload, ctx)


def _extract_model_row(rid: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Pull comparable fields from a stored result without inventing any."""
    res = entry["result"]
    kind = res.get("kind", "exploratory")
    row: dict[str, Any] = {"result_id": rid, "tool": entry["tool"], "kind": kind}
    fit = res.get("fit", res)
    for key in (
        "sources",
        "weights",
        "left",
        "right",
        "se",
        "distance",
        "quality",
        "p",
        "p_value",
        "chisq",
        "dof",
        "f4rank",
        "feasibility",
        "feasible",
        "n_snps",
        "target",
    ):
        if isinstance(fit, dict) and key in fit:
            row[key] = fit[key]
        elif key in res:
            row[key] = res[key]
    return row


def _p_value(row: dict[str, Any]) -> float | None:
    v = row.get("p_value", row.get("p"))
    return float(v) if isinstance(v, int | float) else None


def _is_feasible(row: dict[str, Any]) -> bool:
    """Feasibility from the qpAdm result's own verdict, never re-derived from weights."""
    feas = row.get("feasibility")
    if isinstance(feas, dict) and feas.get("verdict"):
        return str(feas["verdict"]) not in {"infeasible", "rejected"}
    if isinstance(row.get("feasible"), bool):
        return bool(row["feasible"])
    return True


def _aic_like(row: dict[str, Any]) -> float | None:
    """chi-square + 2 * (number of mixture weights), for formal fits only."""
    chisq, weights = row.get("chisq"), row.get("weights")
    if not isinstance(chisq, int | float) or not isinstance(weights, list | dict):
        return None
    return float(chisq) + 2.0 * len(weights)


async def compare_models(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    rows_exp: list[dict[str, Any]] = []
    rows_formal: list[dict[str, Any]] = []
    missing: list[str] = []
    for rid in args["result_ids"]:
        entry = ctx.results.get(rid)
        if entry is None:
            missing.append(rid)
            continue
        row = _extract_model_row(rid, entry)
        (rows_formal if row["kind"] == "formal" else rows_exp).append(row)
    if missing:
        raise ToolInputError(f"unknown result_ids: {', '.join(missing)}")

    def dist(r: dict[str, Any]) -> float:
        v = r.get("distance", r.get("residual_distance"))
        return float(v) if isinstance(v, int | float) else math.inf

    rows_exp.sort(key=dist)
    alpha = float(args.get("alpha", 0.05))
    for r in rows_formal:
        p = _p_value(r)
        r["not_rejected"] = bool(p is not None and p >= alpha and _is_feasible(r))
        r["aic_like"] = _aic_like(r)
    rows_formal.sort(key=lambda r: (not r["not_rejected"], -(_p_value(r) or 0.0)))
    notes = [
        "Exploratory and formal results are tabulated separately and are never ranked together.",
        "Exploratory rows are ordered by fit distance in their coordinate space; distances are "
        "only comparable within the same space and target.",
        f"Formal rows: a model is 'not rejected' if p >= {alpha} and all weights are feasible. "
        "Non-rejection does not prove a model; several models can fit. aic_like = chisq + "
        "2 x number of sources and is only comparable across models with the same target and "
        "right set.",
    ]
    spaces = {ctx.results.get(r["result_id"])["result"].get("space") for r in rows_exp}  # type: ignore[index]
    if len(spaces - {None}) > 1:
        notes.append("Warning: exploratory rows come from different coordinate spaces.")
    return {"exploratory_table": rows_exp, "formal_table": rows_formal, "notes": notes}


async def retrieve_knowledge(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    kb = await asyncio.to_thread(_knowledge, ctx)
    hits = kb.search(args["query"], int(args.get("k", 5)), source=args.get("source"))
    return {
        "query": args["query"],
        "chunks": [c.to_result(s) for c, s in hits],
        "citation_format": "Cite as [chunk_id].",
    }


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


async def propose_reference_sets(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Candidate sources and right/outgroup populations from metadata + nearest distances."""
    space = args.get("space") or ctx.default_space
    ref = _reference(ctx)
    tgt = await _resolve_target(ctx, args["target"], space)
    names, mat = await _call(ref.coordinates, space)
    meta = {
        m.get("id"): m
        for m in await _call(ref.all_metadata)
        if m.get("kind", "population") == "population"
    }
    d = np.sqrt(((mat - tgt.coords[None, :]) ** 2).sum(axis=1))
    order = list(np.argsort(d, kind="stable"))

    tmeta = meta.get(tgt.population) if tgt.population else None
    t_date = _num(args.get("target_date_bp", (tmeta or {}).get("date_bp")))
    t_loc = None
    if args.get("target_lat") is not None and args.get("target_lon") is not None:
        t_loc = (float(args["target_lat"]), float(args["target_lon"]))
    elif tmeta and _num(tmeta.get("lat")) is not None and _num(tmeta.get("lon")) is not None:
        t_loc = (float(tmeta["lat"]), float(tmeta["lon"]))
    min_samples = int(args.get("min_samples", 3))
    n_sources = int(args.get("n_sources", 8))
    n_right = int(args.get("n_right", 8))
    include = [s for s in args.get("include", [])]
    exclude = set(args.get("exclude", [])) | ({tgt.population} if tgt.population else set())
    regions = {r.lower() for r in args.get("source_regions", [])}

    def info(i: int) -> dict[str, Any]:
        n = names[i]
        m = meta.get(n, {})
        row: dict[str, Any] = {"population": n, "distance": round(float(d[i]), 6)}
        for key in ("region", "period", "date_bp", "n_samples", "lat", "lon", "publication"):
            if m.get(key) is not None:
                row[key] = m[key]
        loc = (_num(m.get("lat")), _num(m.get("lon")))
        if t_loc and loc[0] is not None and loc[1] is not None:
            row["km_from_target"] = round(_haversine_km(t_loc, (loc[0], loc[1])))
        return row

    sources: list[dict[str, Any]] = []
    for i in order:
        n = names[i]
        m = meta.get(n, {})
        if n in exclude:
            continue
        ns = _num(m.get("n_samples"))
        if ns is not None and ns < min_samples:
            continue
        dbp = _num(m.get("date_bp"))
        # A proximal source should predate (or be roughly contemporaneous with) the target.
        if t_date is not None and dbp is not None and dbp < t_date - 500:
            continue
        if regions and str(m.get("region", "")).lower() not in regions:
            continue
        row = info(i)
        reasons = [f"rank {len(sources) + 1} by {space} distance"]
        if t_date is not None and dbp is not None:
            reasons.append(f"date {int(dbp)} BP is not younger than target ({int(t_date)} BP)")
        if "km_from_target" in row:
            reasons.append(f"{row['km_from_target']} km from target")
        row["rationale"] = "; ".join(reasons)
        sources.append(row)
        if len(sources) >= n_sources:
            break

    chosen_src = {s["population"] for s in sources}
    # Right set: populations far from the target and from each other, well sampled, ideally
    # anchored by a deeply diverged outgroup. Greedy max-min selection in coordinate space.
    pool = [
        i
        for i in order[::-1]
        if names[i] not in exclude
        and names[i] not in chosen_src
        and (_num(meta.get(names[i], {}).get("n_samples")) or min_samples) >= min_samples
    ]
    right_idx: list[int] = []
    for anchor in args.get("right_anchors", []):
        if anchor in names and anchor not in chosen_src:
            right_idx.append(names.index(anchor))
    if not right_idx and pool:
        right_idx.append(pool[0])
    while len(right_idx) < n_right and pool:
        best, best_score = None, -1.0
        for i in pool:
            if i in right_idx:
                continue
            md = min(float(np.linalg.norm(mat[i] - mat[j])) for j in right_idx)
            if md > best_score:
                best, best_score = i, md
        if best is None:
            break
        right_idx.append(best)
    right = []
    for rank, i in enumerate(right_idx):
        row = info(i)
        row["rationale"] = (
            "user-specified anchor"
            if names[i] in args.get("right_anchors", [])
            else (
                "most distant from target"
                if rank == 0
                else "maximises minimum distance to the right populations already chosen"
            )
        )
        right.append(row)
    for inc in include:
        if inc not in chosen_src and inc in names:
            row = info(names.index(inc))
            row["rationale"] = "requested by hypothesis"
            sources.append(row)

    return {
        "target": tgt.label,
        "space": space,
        "hypothesis": args.get("hypothesis"),
        "candidate_sources": sources,
        "right_populations": right,
        "rationale": [
            "Candidate sources are the closest well-sampled populations in the coordinate space, "
            "filtered to those not younger than the target when dates are known.",
            "Right populations are chosen to be diverse (greedy max-min distance) and to "
            "exclude all candidate sources, so they can differentiate the sources.",
            "This is a starting point only. For qpAdm, right populations must be differentially "
            "related to the sources and must not share drift with the target that the sources "
            "lack; check with run_qpadm_rotate (rotating right) and consult retrieve_knowledge "
            "on choosing right populations.",
        ],
        "kind": "exploratory",
    }


# ---- registry --------------------------------------------------------------------------------

Handler = Callable[[dict[str, Any], ToolContext], Awaitable[dict[str, Any]]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    stores_result: bool = False

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name, description=self.description, input_schema=self.input_schema
        )


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


_SPACE = {
    "type": "string",
    "description": "Coordinate space: 'g25' (user Global25-style) or 'strata-pca-v1'.",
}
_POPS = {"type": "array", "items": {"type": "string"}, "minItems": 1}

TOOLS: list[Tool] = [
    Tool(
        "search_populations",
        "Search the reference library by free text, region and/or period. Returns each "
        "population's id and group_id with basic metadata (region, period, dates, sample "
        "count, publication). Use id for coordinate tools and group_id for qpAdm/f4 tools. "
        "`in_f2_cache` says whether a population can be used in qpAdm/f4 at all; formal "
        "tools reject any population without it. Region and period are exact filters over "
        "the library's own labels; leave them out unless you know a label, and a search that "
        "finds nothing returns the accepted labels.",
        _obj(
            {
                "query": {"type": "string"},
                "region": {"type": "string"},
                "period": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            [],
        ),
        search_populations,
    ),
    Tool(
        "get_population",
        "Full metadata for one reference population: samples, dates, location, publication.",
        _obj({"population_id": {"type": "string"}}, ["population_id"]),
        get_population,
    ),
    Tool(
        "describe_reference_panel",
        "What the installed reference panel is made of, and what it cannot answer. Returns "
        "`right_set`, the curated deep-outgroup set as it resolved in this release — start a "
        "qpAdm right set from it rather than choosing outgroups yourself — plus `limits`, the "
        "questions this panel cannot answer, and the labels the release does not carry. Call "
        "this before the first formal model of a conversation.",
        _obj({}, []),
        describe_reference_panel,
    ),
    Tool(
        "list_user_datasets",
        "List the user's uploaded datasets: IDs, kind and QC summary only (no genotypes).",
        _obj({}, []),
        list_user_datasets,
    ),
    Tool(
        "nearest_populations",
        "EXPLORATORY. Rank reference populations by Euclidean distance to the target in a "
        "coordinate space.",
        _obj(
            {
                "target": TARGET_SCHEMA,
                "space": _SPACE,
                "k": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ["target"],
        ),
        nearest_populations,
        stores_result=True,
    ),
    Tool(
        "fit_admixture",
        "EXPLORATORY. Fit the target as a non-negative, sum-to-one mixture of source population "
        "means in a coordinate space (G25/PCA). Optional bootstrap gives weight CIs. Not a formal "
        "test - confirm with run_qpadm.",
        _obj(
            {
                "target": TARGET_SCHEMA,
                "space": _SPACE,
                "sources": _POPS,
                "method": {"type": "string", "enum": ["qp", "nnls", "slsqp"]},
                "bootstrap": {"type": "boolean"},
                "n_bootstrap": {"type": "integer", "minimum": 20, "maximum": 2000},
                "seed": {"type": "integer"},
            },
            ["target", "sources"],
        ),
        fit_admixture,
        stores_result=True,
    ),
    Tool(
        "rotate_sources",
        "EXPLORATORY. Try many source combinations (k_min..k_max sources) from candidates and "
        "rank by fit distance with a parsimony filter.",
        _obj(
            {
                "target": TARGET_SCHEMA,
                "space": _SPACE,
                "candidates": _POPS,
                "k_min": {"type": "integer", "minimum": 1, "maximum": 6},
                "k_max": {"type": "integer", "minimum": 1, "maximum": 6},
                "max_models": {"type": "integer", "minimum": 1, "maximum": 20000},
                "method": {"type": "string", "enum": ["qp", "nnls", "slsqp"]},
                "seed": {"type": "integer"},
            },
            ["target", "candidates"],
        ),
        rotate_sources,
        stores_result=True,
    ),
    Tool(
        "sensitivity_analysis",
        "EXPLORATORY. Leave-one-source-out and leave-one-dimension-out changes for a fitted "
        "model, to test how fragile the weights are.",
        _obj(
            {
                "target": TARGET_SCHEMA,
                "space": _SPACE,
                "sources": _POPS,
                "method": {"type": "string", "enum": ["qp", "nnls", "slsqp"]},
                "seed": {"type": "integer"},
            },
            ["target", "sources"],
        ),
        sensitivity_analysis,
        stores_result=True,
    ),
    Tool(
        "run_qpadm",
        "FORMAL. Run qpAdm (ADMIXTOOLS 2): test whether the target is a mixture of the given "
        "source populations, using the right (outgroup) populations as the scaffold. Requires "
        "strictly MORE right than source populations, all names distinct and disjoint. Returns "
        "weights with SE and Z, p-value, chi-square, rank-drop and pop-drop tables and a "
        "feasibility verdict whose 'reasons' you should quote: 'plausible' means NOT REJECTED, "
        "never proven. Use each population's group_id (from search_populations or "
        "get_population), not its id: qpAdm keys on the group label stored in the f2 cache.",
        _obj(
            {
                "target": {"type": "string"},
                "sources": _POPS,
                "right": _POPS,
                "allsnps": {"type": "boolean"},
            },
            ["target", "sources", "right"],
        ),
        run_qpadm,
        stores_result=True,
    ),
    Tool(
        "run_qpadm_rotate",
        "FORMAL. Rotate a candidate pool between source and right roles: every candidate not "
        "used as a source becomes a right population, plus any populations in 'right' which "
        "stay on the right in every model. Keep the pool under about 10 names and "
        "max_sources at 2-3, or enumeration is refused. Use group_id values, not ids. "
        "Rotation p-values are NOT corrected for multiple testing; report n_models_tested "
        "alongside any ranking.",
        _obj(
            {
                "target": {"type": "string"},
                "candidates": _POPS,
                "right": _POPS,
                "max_sources": {"type": "integer", "minimum": 1, "maximum": 4},
                "max_models": {"type": "integer", "minimum": 1, "maximum": 2000},
            },
            ["target", "candidates", "right"],
        ),
        run_qpadm_rotate,
        stores_result=True,
    ),
    Tool(
        "run_f4",
        "FORMAL. Compute f4(A,B;C,D) for each given quadruple, with block-jackknife SE and "
        "Z-scores, using group_id values. |Z| >= 3 is the conventional significance "
        "threshold; f4 near zero is consistent with the tree (A,B)(C,D) and does not prove it.",
        _obj(
            {
                "quadruples": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 50,
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                }
            },
            ["quadruples"],
        ),
        run_f4,
        stores_result=True,
    ),
    Tool(
        "compare_models",
        "Tabulate previously computed results (by result_id) side by side. Exploratory and "
        "formal results go in separate tables and are never ranked together.",
        _obj(
            {
                "result_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "alpha": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
            },
            ["result_ids"],
        ),
        compare_models,
    ),
    Tool(
        "retrieve_knowledge",
        "Search the Strata methods corpus and reference-library metadata. Returns chunks with "
        "chunk_id for citation as [chunk_id].",
        _obj(
            {
                "query": {"type": "string", "minLength": 2},
                "k": {"type": "integer", "minimum": 1, "maximum": 10},
                "source": {"type": "string", "enum": ["methods", "reference"]},
            },
            ["query"],
        ),
        retrieve_knowledge,
    ),
    Tool(
        "propose_reference_sets",
        "Propose candidate sources and right (outgroup) populations for a target and "
        "hypothesis, using geographic/temporal metadata and coordinate distance, with stated "
        "rationale. A starting point to be tested, not a conclusion.",
        _obj(
            {
                "target": TARGET_SCHEMA,
                "space": _SPACE,
                "hypothesis": {"type": "string"},
                "target_date_bp": {"type": "number"},
                "target_lat": {"type": "number", "minimum": -90, "maximum": 90},
                "target_lon": {"type": "number", "minimum": -180, "maximum": 180},
                "source_regions": {"type": "array", "items": {"type": "string"}},
                "include": {"type": "array", "items": {"type": "string"}},
                "exclude": {"type": "array", "items": {"type": "string"}},
                "right_anchors": {"type": "array", "items": {"type": "string"}},
                "n_sources": {"type": "integer", "minimum": 1, "maximum": 30},
                "n_right": {"type": "integer", "minimum": 3, "maximum": 30},
                "min_samples": {"type": "integer", "minimum": 1},
            },
            ["target"],
        ),
        propose_reference_sets,
    ),
]

TOOLS_BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}


def tool_specs(names: list[str] | None = None) -> list[ToolSpec]:
    return [t.spec() for t in TOOLS if names is None or t.name in names]


@dataclass
class ToolOutcome:
    ok: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0

    def content(self) -> str:
        """JSON string given back to the model."""
        if self.ok:
            return json.dumps(self.result, default=str, allow_nan=False)
        return json.dumps({"error": self.error})


async def execute_tool(
    name: str, arguments: dict[str, Any], ctx: ToolContext, *, parse_error: str | None = None
) -> ToolOutcome:
    """Validate and run one tool call; every failure becomes a tool error, never an exception."""
    t0 = time.perf_counter()

    def done(
        ok: bool, result: dict[str, Any] | None = None, error: str | None = None
    ) -> ToolOutcome:
        return ToolOutcome(ok, result, error, int((time.perf_counter() - t0) * 1000))

    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return done(False, error=f"unknown tool {name!r}")
    if parse_error:
        return done(False, error=f"INVALID_JSON: {parse_error}")
    try:
        jsonschema.validate(arguments, tool.input_schema)
    except jsonschema.ValidationError as exc:
        return done(False, error=f"invalid arguments: {exc.message}")
    try:
        result = await tool.handler(arguments, ctx)
        result = _jsonable(result)
        if tool.stores_result:
            result["result_id"] = ctx.results.put(name, result)
        # Ensure the payload serialises (NaN/inf would be rejected by allow_nan=False).
        json.dumps(result, default=str, allow_nan=False)
        return done(True, result=result)
    except (ToolUnavailableError, ToolInputError, KeyError, ValueError, TypeError) as exc:
        return done(False, error=f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as a tool error
        return done(False, error=f"internal error in {name}: {type(exc).__name__}: {exc}")
