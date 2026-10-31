from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select

from strata.api import datasets as dsvc
from strata.api import science
from strata.api.deps import DbDep, PrincipalDep, SettingsDep, owner_expiry, rate_limit_expensive
from strata.api.errors import ApiError, not_found
from strata.api.routers.jobs import job_out
from strata.api.schemas import (
    AnalysisCreate,
    AnalysisCreated,
    AnalysisOut,
    ComparisonCreate,
    ComparisonOut,
)
from strata.db.models import Analysis, Dataset, Job, ModelComparison
from strata.db.types import utcnow
from strata.jobs.runner import submit
from strata.reports import build_bundle, render_html
from strata.security.headers import REPORT_CSP

router = APIRouter(tags=["analyses"])

FORMAL = {"qpadm", "qpadm_rotate"}


def analysis_out(a: Analysis) -> AnalysisOut:
    ids = [uuid.UUID(str(i)) for i in a.dataset_ids or []]
    return AnalysisOut(
        id=a.id,
        kind=a.kind,
        title=a.title,
        status=a.status,  # type: ignore[arg-type]
        dataset_id=ids[0] if ids else None,
        dataset_ids=ids,
        params=a.params,
        result=a.result,
        error=a.error,
        provenance=a.provenance,
        job_id=a.job_id,
        created_at=a.created_at,
        finished_at=a.finished_at,
        expires_at=a.expires_at,
    )


def _owned(db: DbDep, principal: PrincipalDep, analysis_id: uuid.UUID) -> Analysis:
    a = db.get(Analysis, analysis_id)
    if a is None or a.owner_id != principal.user_id:
        raise not_found("analysis")
    return a


@router.post(
    "/analyses",
    response_model=AnalysisCreated,
    status_code=201,
    dependencies=[Depends(rate_limit_expensive)],
    summary="Create an analysis (job)",
)
def create_analysis(
    body: AnalysisCreate, db: DbDep, principal: PrincipalDep, settings: SettingsDep
) -> AnalysisCreated:
    """Creates the analysis and its job. In `inline` job mode the job runs before this
    returns; in `queue` mode poll `GET /jobs/{id}`. G25/PCA kinds produce *exploratory*
    results; `qpadm` / `qpadm_rotate` produce *formal* f-statistics tests."""
    params: dict[str, Any] = dict(body.params)
    dataset_ids: list[str] = []
    if body.dataset_id is not None:
        dsvc.get_owned(db, principal, body.dataset_id)
        dataset_ids.append(str(body.dataset_id))
    src = params.get("source_dataset_id")
    if src:
        try:
            src_id = uuid.UUID(str(src))
        except ValueError as exc:
            raise ApiError(422, "source_dataset_id must be a UUID", "invalid_input") from exc
        dsvc.get_owned(db, principal, src_id)
        dataset_ids.append(str(src_id))
    if body.target is not None:
        params["target"] = body.target
    if body.kind in FORMAL and settings.job_mode == "inline" and not science.qpadm_available():
        raise ApiError(
            503,
            "qpAdm is unavailable on this server (needs R + ADMIXTOOLS 2; run "
            "the worker image or set STRATA_JOB_MODE=queue)",
            "qpadm_unavailable",
        )
    if body.kind not in FORMAL and body.dataset_id is None and not params.get("target"):
        raise ApiError(
            422, "exploratory analyses need dataset_id or a reference target", "invalid_input"
        )
    a = Analysis(
        id=uuid.uuid4(),
        owner_id=principal.user_id,
        kind=body.kind,
        title=body.title,
        params=params,
        dataset_ids=dataset_ids,
        status="queued",
        expires_at=owner_expiry(db, principal),
    )
    db.add(a)
    db.flush()
    job = submit(
        db, body.kind, {"analysis_id": str(a.id)}, owner_id=principal.user_id, settings=settings
    )
    a = db.get(Analysis, a.id)
    assert a is not None
    if a.job_id is None:
        a.job_id = job.id
        db.flush()
    return AnalysisCreated(analysis=analysis_out(a), job=job_out(job))


@router.get("/analyses", response_model=list[AnalysisOut], summary="List my analyses")
def list_analyses(
    db: DbDep, principal: PrincipalDep, limit: int = Query(100, ge=1, le=500)
) -> list[AnalysisOut]:
    rows = db.scalars(
        select(Analysis)
        .where(Analysis.owner_id == principal.user_id)
        .order_by(Analysis.created_at.desc())
        .limit(limit)
    )
    return [analysis_out(a) for a in rows]


@router.get("/analyses/{analysis_id}", response_model=AnalysisOut, summary="Analysis detail")
def get_analysis(analysis_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> AnalysisOut:
    return analysis_out(_owned(db, principal, analysis_id))


@router.delete("/analyses/{analysis_id}", status_code=204, summary="Delete an analysis")
def delete_analysis(analysis_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> Response:
    a = _owned(db, principal, analysis_id)
    if a.job_id:
        job = db.get(Job, a.job_id)
        if job is not None and job.status in ("queued", "running"):
            from strata.jobs.queue import cancel

            cancel(db, job)
    db.delete(a)
    return Response(status_code=204)


@router.get(
    "/analyses/{analysis_id}/report",
    summary="Reproducible report (HTML or JSON)",
    responses={200: {"content": {"text/html": {}, "application/json": {}}}},
)
def report(
    analysis_id: uuid.UUID,
    db: DbDep,
    principal: PrincipalDep,
    format: str = Query("html", pattern="^(html|json)$"),
) -> Response:
    a = _owned(db, principal, analysis_id)
    if a.status != "succeeded":
        raise ApiError(409, f"analysis is {a.status}; reports need a finished analysis", "conflict")
    datasets = [d for d in (db.get(Dataset, uuid.UUID(str(i))) for i in a.dataset_ids) if d]
    bundle = build_bundle(a, datasets, generated_at=utcnow())
    stem = f"strata-report-{a.id}"
    if format == "json":
        return JSONResponse(
            bundle, headers={"Content-Disposition": f'attachment; filename="{stem}.json"'}
        )
    return HTMLResponse(
        render_html(bundle),
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.html"',
            "Content-Security-Policy": REPORT_CSP,
        },
    )


# ------------------------------------------------------------------ saved model comparisons


def _comparison_summary(rows: list[Analysis]) -> dict[str, Any]:
    out = []
    for a in rows:
        r = a.result or {}
        out.append(
            {
                "analysis_id": str(a.id),
                "kind": a.kind,
                "title": a.title,
                "classification": r.get("kind"),
                "target": r.get("target"),
                "distance": r.get("distance"),
                "p_value": r.get("p_value"),
                "feasible": r.get("feasible"),
                "weights": r.get("weights"),
            }
        )
    return {"models": out}


@router.post(
    "/comparisons",
    response_model=ComparisonOut,
    status_code=201,
    tags=["comparisons"],
    summary="Save a side-by-side model comparison",
)
def create_comparison(body: ComparisonCreate, db: DbDep, principal: PrincipalDep) -> Any:
    rows = [_owned(db, principal, i) for i in body.analysis_ids]
    c = ModelComparison(
        owner_id=principal.user_id,
        name=body.name,
        analysis_ids=[str(i) for i in body.analysis_ids],
        notes=body.notes,
        summary=_comparison_summary(rows),
        expires_at=owner_expiry(db, principal),
    )
    db.add(c)
    db.flush()
    return c


@router.get(
    "/comparisons",
    response_model=list[ComparisonOut],
    tags=["comparisons"],
    summary="List saved comparisons",
)
def list_comparisons(db: DbDep, principal: PrincipalDep) -> Any:
    return list(
        db.scalars(
            select(ModelComparison)
            .where(ModelComparison.owner_id == principal.user_id)
            .order_by(ModelComparison.created_at.desc())
        )
    )


@router.delete(
    "/comparisons/{comparison_id}",
    status_code=204,
    tags=["comparisons"],
    summary="Delete a saved comparison",
)
def delete_comparison(comparison_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> Response:
    c = db.get(ModelComparison, comparison_id)
    if c is None or c.owner_id != principal.user_id:
        raise not_found("comparison")
    db.delete(c)
    return Response(status_code=204)
