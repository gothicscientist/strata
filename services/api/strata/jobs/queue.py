"""Durable job queue on the application database.

Postgres: claims use `SELECT ... FOR UPDATE SKIP LOCKED`, so any number of workers can poll
concurrently without double-claiming or blocking on each other's locked rows.
SQLite (dev/tests): a single-statement compare-and-set `UPDATE ... WHERE status='queued'`;
SQLite serialises writers, so the CAS is equally exclusive.
"""

from __future__ import annotations

import logging
import traceback
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select, text, update
from sqlalchemy.orm import Session

from strata.db.models import Analysis, Job
from strata.db.types import utcnow

log = logging.getLogger("strata.jobs")

TERMINAL = {"succeeded", "failed", "cancelled"}


class PermanentJobError(Exception):
    """Failure that retrying cannot fix (bad parameters, missing inputs)."""


class JobTimeoutError(Exception):
    pass


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any],
    *,
    owner_id: uuid.UUID | None = None,
    priority: int = 100,
    max_attempts: int = 3,
    timeout_s: int | None = None,
    run_after: datetime | None = None,
) -> Job:
    from strata.jobs.registry import get_handler

    get_handler(kind)  # unknown kinds fail at enqueue time, not in the worker
    job = Job(
        id=uuid.uuid4(), kind=kind, payload=payload, owner_id=owner_id, priority=priority,
        max_attempts=max_attempts, timeout_s=timeout_s, run_after=run_after or utcnow(),
        status="queued",
    )
    session.add(job)
    session.flush()
    return job


def claim(engine: Engine, worker_id: str, kinds: list[str] | None = None) -> uuid.UUID | None:
    """Atomically claim the next runnable job and mark it running. Returns its id."""
    now = utcnow()
    with Session(engine) as s, s.begin():
        if engine.dialect.name == "postgresql":
            kind_sql = "AND kind = ANY(:kinds)" if kinds else ""
            row = s.execute(
                text(
                    f"""
                    SELECT id FROM jobs
                    WHERE status = 'queued' AND run_after <= :now {kind_sql}
                    ORDER BY priority, run_after, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """
                ),
                {"now": now, "kinds": kinds},
            ).first()
            if row is None:
                return None
            job_id = row[0]
            s.execute(
                update(Job).where(Job.id == job_id).values(
                    status="running", locked_by=worker_id, started_at=now, heartbeat_at=now,
                    attempts=Job.attempts + 1,
                )
            )
            return job_id
        # SQLite / generic: optimistic CAS, retried if another worker won the race.
        for _ in range(5):
            q = select(Job.id).where(Job.status == "queued", Job.run_after <= now)
            if kinds:
                q = q.where(Job.kind.in_(kinds))
            job_id = s.scalar(q.order_by(Job.priority, Job.run_after, Job.created_at).limit(1))
            if job_id is None:
                return None
            res = s.execute(
                update(Job).where(Job.id == job_id, Job.status == "queued").values(
                    status="running", locked_by=worker_id, started_at=now, heartbeat_at=now,
                    attempts=Job.attempts + 1,
                ).execution_options(synchronize_session=False)
            )
            if res.rowcount == 1:
                return job_id
        return None


def heartbeat(engine: Engine, job_id: uuid.UUID, worker_id: str) -> bool:
    """Refresh the lease. False if the job is no longer ours (reaped or cancelled)."""
    with Session(engine) as s, s.begin():
        res = s.execute(
            update(Job).where(Job.id == job_id, Job.locked_by == worker_id,
                              Job.status == "running").values(heartbeat_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        return res.rowcount == 1


def backoff_delay(attempt: int, base_s: float, cap_s: float = 900.0) -> float:
    return min(cap_s, base_s * (2 ** max(attempt - 1, 0)))


def complete(session: Session, job: Job, result: dict[str, Any]) -> None:
    job.status = "succeeded"
    job.result = result
    job.error = None
    job.finished_at = utcnow()
    job.locked_by = None


def fail(
    session: Session, job: Job, error: str, *, retryable: bool, backoff_base_s: float
) -> None:
    if retryable and job.attempts < job.max_attempts:
        job.status = "queued"
        job.run_after = utcnow() + timedelta(seconds=backoff_delay(job.attempts, backoff_base_s))
        job.error = f"attempt {job.attempts} failed: {error}"
        job.locked_by = None
        job.heartbeat_at = None
        return
    job.status = "failed"
    job.error = error
    job.finished_at = utcnow()
    job.locked_by = None
    _mark_analysis_failed(session, job, error)


def _mark_analysis_failed(session: Session, job: Job, error: str) -> None:
    aid = (job.payload or {}).get("analysis_id")
    if not aid:
        return
    analysis = session.get(Analysis, uuid.UUID(str(aid)))
    if analysis is not None and analysis.status not in TERMINAL:
        analysis.status = "failed"
        analysis.error = error
        analysis.finished_at = utcnow()


def cancel(session: Session, job: Job) -> bool:
    if job.status in TERMINAL:
        return False
    job.status = "cancelled"
    job.finished_at = utcnow()
    job.locked_by = None
    aid = (job.payload or {}).get("analysis_id")
    if aid:
        a = session.get(Analysis, uuid.UUID(str(aid)))
        if a is not None and a.status not in TERMINAL:
            a.status = "cancelled"
            a.finished_at = job.finished_at
    return True


def reap_stale(session: Session, *, stale_after_s: float, backoff_base_s: float) -> int:
    """Requeue (or fail) running jobs whose worker stopped heartbeating (crash, OOM, kill)."""
    cutoff = utcnow() - timedelta(seconds=stale_after_s)
    n = 0
    for job in session.scalars(
        select(Job).where(Job.status == "running", Job.heartbeat_at < cutoff).with_for_update(
            skip_locked=True
        )
    ):
        fail(session, job, "worker lost (heartbeat timeout)", retryable=True,
             backoff_base_s=backoff_base_s)
        n += 1
    return n


def is_retryable(exc: BaseException) -> bool:
    from sqlalchemy.exc import OperationalError

    if isinstance(exc, PermanentJobError | ValueError | TypeError | KeyError | LookupError):
        return False
    if isinstance(exc, JobTimeoutError):
        return False
    return isinstance(exc, OperationalError | ConnectionError | TimeoutError | OSError)


def format_error(exc: BaseException) -> str:
    # Messages only: tracebacks can contain locals; never include payload data.
    msg = f"{type(exc).__name__}: {exc}"
    return msg[:2000]


def format_traceback(exc: BaseException) -> str:
    return "".join(traceback.format_exception_only(type(exc), exc))[:2000]
