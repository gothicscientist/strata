from __future__ import annotations

import uuid

from fastapi import APIRouter

from strata.api.deps import DbDep, PrincipalDep
from strata.api.errors import ApiError, not_found
from strata.api.schemas import JobOut
from strata.db.models import Job
from strata.jobs import queue

router = APIRouter(prefix="/jobs", tags=["jobs"])


def job_out(job: Job) -> JobOut:
    aid = (job.payload or {}).get("analysis_id")
    return JobOut(
        id=job.id, kind=job.kind, status=job.status, error=job.error,  # type: ignore[arg-type]
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at,
        attempts=job.attempts, max_attempts=job.max_attempts,
        analysis_id=uuid.UUID(str(aid)) if aid else None, result=job.result,
    )


def _owned(db: DbDep, principal: PrincipalDep, job_id: uuid.UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.owner_id != principal.user_id:
        raise not_found("job")
    return job


@router.get("/{job_id}", response_model=JobOut, summary="Job status")
def get_job(job_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> JobOut:
    return job_out(_owned(db, principal, job_id))


@router.post("/{job_id}/cancel", response_model=JobOut, summary="Cancel a queued/running job")
def cancel_job(job_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> JobOut:
    job = _owned(db, principal, job_id)
    if not queue.cancel(db, job):
        raise ApiError(409, f"job already {job.status}", "conflict")
    db.flush()
    return job_out(job)
