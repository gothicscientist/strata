"""Executes one claimed job: heartbeats, timeout, retry/backoff bookkeeping, commit."""

from __future__ import annotations

import concurrent.futures as cf
import logging
import threading
import time
import uuid
from typing import Any

from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from strata.config import Settings
from strata.db.models import Job
from strata.db.types import utcnow
from strata.jobs import queue
from strata.jobs.registry import JobCancelledError, JobContext, get_spec

log = logging.getLogger("strata.jobs")


class _Heartbeat(threading.Thread):
    def __init__(self, engine: Engine, job_id: uuid.UUID, worker_id: str, every_s: float,
                 ctx: JobContext) -> None:
        super().__init__(daemon=True, name=f"heartbeat-{job_id}")
        self.engine, self.job_id, self.worker_id, self.every_s = engine, job_id, worker_id, every_s
        self.ctx = ctx
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.wait(self.every_s):
            try:
                if not queue.heartbeat(self.engine, self.job_id, self.worker_id):
                    # Cancelled by a user or reaped: tell the handler to stop.
                    self.ctx.cancel()
                    return
            except Exception:  # noqa: BLE001 - transient DB error; next beat retries
                log.warning("heartbeat failed for job %s", self.job_id)


class WorkerMustExitError(Exception):
    """A handler thread overran its timeout; the process should be restarted cleanly."""


def run_claimed(
    engine: Engine, job_id: uuid.UUID, worker_id: str, settings: Settings, *, threaded: bool
) -> str:
    """Run a job already marked running by `claim`. Returns the job's resulting status."""
    session = Session(engine, expire_on_commit=False)
    job = session.get(Job, job_id)
    if job is None:
        session.close()
        return "missing"
    spec = get_spec(job.kind)
    timeout = float(job.timeout_s or spec.timeout_s or settings.job_timeout_s)
    ctx = JobContext(
        job_id=job.id, kind=job.kind, owner_id=job.owner_id, payload=dict(job.payload or {}),
        session=session, settings=settings, attempt=job.attempts,
        deadline=time.monotonic() + timeout,
    )
    hb = _Heartbeat(engine, job.id, worker_id, settings.job_heartbeat_s, ctx)
    hb.start()
    t0 = time.monotonic()
    overran = False
    try:
        if threaded:
            pool = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"job-{job.kind}")
            fut = pool.submit(spec.handler, ctx)
            try:
                result = fut.result(timeout=timeout)
            except cf.TimeoutError:
                ctx.cancel()
                overran = True
                raise queue.JobTimeoutError(f"job exceeded {timeout:.0f}s") from None
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
        else:
            result = spec.handler(ctx)
        ctx.check()
        job = session.get(Job, job_id)
        assert job is not None
        if job.status == "cancelled":
            session.rollback()
            return "cancelled"
        result = dict(result or {})
        result.setdefault("duration_s", round(time.monotonic() - t0, 3))
        queue.complete(session, job, result)
        session.commit()
        log.info("job %s (%s) succeeded in %.2fs", job_id, spec.kind, time.monotonic() - t0)
        return "succeeded"
    except BaseException as exc:  # noqa: BLE001 - every failure must be recorded
        if isinstance(exc, KeyboardInterrupt | SystemExit):
            _requeue_after_interrupt(engine, job_id)
            raise
        if not overran:
            session.rollback()
        return _record_failure(engine, job_id, exc, settings, overran)
    finally:
        hb.stop.set()
        if not overran:
            session.close()
        if overran:
            raise WorkerMustExitError(str(job_id))


def _record_failure(engine: Engine, job_id: uuid.UUID, exc: BaseException, settings: Settings,
                    overran: bool) -> str:
    if isinstance(exc, JobCancelledError):
        with Session(engine) as s, s.begin():
            j = s.get(Job, job_id)
            if j is not None and j.status == "running":
                queue.cancel(s, j)
        return "cancelled"
    retryable = queue.is_retryable(exc)
    err = queue.format_error(exc)
    log.warning("job %s failed (retryable=%s): %s", job_id, retryable, err)
    with Session(engine) as s, s.begin():
        j = s.get(Job, job_id)
        if j is None:
            return "missing"
        if j.status == "cancelled":
            return "cancelled"
        queue.fail(s, j, err, retryable=retryable, backoff_base_s=settings.job_backoff_base_s)
        return j.status


def _requeue_after_interrupt(engine: Engine, job_id: uuid.UUID) -> None:
    try:
        with Session(engine) as s, s.begin():
            s.execute(
                update(Job).where(Job.id == job_id, Job.status == "running").values(
                    status="queued", locked_by=None, heartbeat_at=None,
                    attempts=Job.attempts - 1, run_after=utcnow(),
                )
            )
    except Exception:  # noqa: BLE001
        log.exception("could not requeue interrupted job %s", job_id)


def claim_specific(engine: Engine, job_id: uuid.UUID, worker_id: str) -> bool:
    now = utcnow()
    with Session(engine) as s, s.begin():
        res = s.execute(
            update(Job).where(Job.id == job_id, Job.status == "queued").values(
                status="running", locked_by=worker_id, started_at=now, heartbeat_at=now,
                attempts=Job.attempts + 1,
            ).execution_options(synchronize_session=False)
        )
        return res.rowcount == 1


def run_inline(engine: Engine, job_id: uuid.UUID, settings: Settings) -> str:
    """STRATA_JOB_MODE=inline: run synchronously in this process, retrying immediately."""
    worker_id = f"inline-{uuid.uuid4().hex[:8]}"
    status = "queued"
    while status == "queued":
        if not claim_specific(engine, job_id, worker_id):
            with Session(engine) as s:
                j = s.get(Job, job_id)
                return j.status if j else "missing"
        status = run_claimed(engine, job_id, worker_id, settings, threaded=False)
    return status


def submit(session: Session, kind: str, payload: dict[str, Any], *, owner_id: uuid.UUID | None,
           settings: Settings, priority: int = 100) -> Job:
    """Enqueue a job, commit, and in inline mode run it before returning."""
    spec = get_spec(kind)
    job = queue.enqueue(session, kind, payload, owner_id=owner_id, priority=priority,
                        max_attempts=settings.job_max_attempts, timeout_s=spec.timeout_s)
    session.commit()
    if settings.job_mode == "inline":
        bind = session.get_bind()
        engine = bind if isinstance(bind, Engine) else bind.engine
        run_inline(engine, job.id, settings)
        session.expire_all()
        refreshed = session.get(Job, job.id)
        assert refreshed is not None
        return refreshed
    return job
