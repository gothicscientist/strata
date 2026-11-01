"""Queue semantics: exclusive claims under concurrency, retries/backoff, heartbeats, reaping,
timeouts, cancellation, worker lifecycle."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from strata.config import get_settings
from strata.db.models import Job
from strata.db.types import utcnow
from strata.jobs import queue
from strata.jobs.registry import JobContext, kinds, register
from strata.jobs.runner import WorkerMustExitError, run_claimed, run_inline

CALLS: dict[str, int] = {}


@register("test_echo", timeout_s=30)
def _echo(ctx: JobContext) -> dict:
    return {"echo": ctx.payload.get("x")}


@register("test_flaky", timeout_s=30)
def _flaky(ctx: JobContext) -> dict:
    key = ctx.payload["key"]
    CALLS[key] = CALLS.get(key, 0) + 1
    if CALLS[key] < ctx.payload["succeed_on"]:
        raise ConnectionError("transient")
    return {"calls": CALLS[key]}


@register("test_bad", timeout_s=30)
def _bad(ctx: JobContext) -> dict:
    raise ValueError("bad parameters")


@register("test_sleep", timeout_s=1)
def _sleep(ctx: JobContext) -> dict:
    for _ in range(int(ctx.payload.get("steps", 50))):
        time.sleep(0.05)
    return {}


@register("test_coop", timeout_s=30)
def _coop(ctx: JobContext) -> dict:
    while True:  # cooperative handler: stops when cancelled
        ctx.check()
        time.sleep(0.02)


def _enqueue(engine: Engine, kind: str, payload: dict | None = None, **kw) -> uuid.UUID:
    with Session(engine) as s, s.begin():
        return queue.enqueue(s, kind, payload or {}, **kw).id


def _job(engine: Engine, jid: uuid.UUID) -> Job:
    with Session(engine) as s:
        j = s.get(Job, jid)
        assert j is not None
        s.expunge(j)
        return j


def test_builtin_kinds_registered():
    assert {
        "pca_project",
        "admixture_fit",
        "admixture_rotate",
        "qpadm",
        "qpadm_rotate",
        "report",
        "nearest",
    } <= set(kinds())


def test_unknown_kind_rejected(sqlite_engine):
    with pytest.raises(ValueError), Session(sqlite_engine) as s:
        queue.enqueue(s, "nope", {})


def _concurrent_claims(engine: Engine, n_jobs: int, n_workers: int) -> list[uuid.UUID]:
    for i in range(n_jobs):
        _enqueue(engine, "test_echo", {"x": i})
    claimed: list[uuid.UUID] = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_workers)
    errors: list[BaseException] = []

    def worker(w: int) -> None:
        barrier.wait()
        try:
            while (jid := queue.claim(engine, f"w{w}")) is not None:
                with lock:
                    claimed.append(jid)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    assert not errors, errors
    return claimed


def test_concurrent_claims_sqlite_exclusive(sqlite_engine):
    claimed = _concurrent_claims(sqlite_engine, 60, 8)
    assert len(claimed) == 60 and len(set(claimed)) == 60
    with Session(sqlite_engine) as s:
        rows = s.scalars(select(Job)).all()
        assert all(j.status == "running" and j.attempts == 1 for j in rows)


def test_concurrent_claims_postgres_skip_locked(pg_engine):
    claimed = _concurrent_claims(pg_engine, 200, 12)
    assert len(claimed) == 200 and len(set(claimed)) == 200


def test_postgres_skip_locked_does_not_block(pg_engine):
    from sqlalchemy import text

    a = _enqueue(pg_engine, "test_echo", priority=1)
    b = _enqueue(pg_engine, "test_echo", priority=2)
    with pg_engine.connect() as holder:
        tx = holder.begin()
        holder.execute(text("select id from jobs where id = :i for update"), {"i": a})
        t0 = time.monotonic()
        got = queue.claim(pg_engine, "w2")
        assert got == b and time.monotonic() - t0 < 2  # skipped the locked row, no wait
        tx.rollback()
    assert queue.claim(pg_engine, "w3") == a


def test_priority_and_run_after(sqlite_engine):
    later = _enqueue(sqlite_engine, "test_echo", run_after=utcnow() + timedelta(hours=1))
    low = _enqueue(sqlite_engine, "test_echo", priority=200)
    high = _enqueue(sqlite_engine, "test_echo", priority=10)
    assert queue.claim(sqlite_engine, "w") == high
    assert queue.claim(sqlite_engine, "w") == low
    assert queue.claim(sqlite_engine, "w") is None
    assert _job(sqlite_engine, later).status == "queued"


def test_retry_with_backoff_then_success(sqlite_engine):
    s = get_settings()
    jid = _enqueue(
        sqlite_engine, "test_flaky", {"key": uuid.uuid4().hex, "succeed_on": 3}, max_attempts=3
    )
    assert queue.claim(sqlite_engine, "w") == jid
    assert run_claimed(sqlite_engine, jid, "w", s, threaded=False) == "queued"
    j = _job(sqlite_engine, jid)
    assert j.attempts == 1 and j.run_after > utcnow() - timedelta(seconds=1)
    assert "transient" in j.error
    assert run_inline(sqlite_engine, jid, s) == "succeeded"
    j = _job(sqlite_engine, jid)
    assert j.attempts == 3 and j.result["calls"] == 3 and j.error is None


def test_retries_exhausted(sqlite_engine):
    jid = _enqueue(
        sqlite_engine, "test_flaky", {"key": uuid.uuid4().hex, "succeed_on": 99}, max_attempts=2
    )
    assert run_inline(sqlite_engine, jid, get_settings()) == "failed"
    j = _job(sqlite_engine, jid)
    assert j.attempts == 2 and j.finished_at is not None


def test_permanent_error_not_retried(sqlite_engine):
    jid = _enqueue(sqlite_engine, "test_bad", max_attempts=5)
    assert run_inline(sqlite_engine, jid, get_settings()) == "failed"
    j = _job(sqlite_engine, jid)
    assert j.attempts == 1 and j.error == "ValueError: bad parameters"


def test_backoff_delay():
    assert [queue.backoff_delay(a, 5) for a in (1, 2, 3, 4)] == [5, 10, 20, 40]
    assert queue.backoff_delay(30, 5) == 900


def test_reaper_requeues_stale_then_fails(sqlite_engine):
    jid = _enqueue(sqlite_engine, "test_echo", max_attempts=2)
    for attempt in (1, 2):
        assert queue.claim(sqlite_engine, "dead-worker") == jid
        with Session(sqlite_engine) as s, s.begin():
            s.get(Job, jid).heartbeat_at = utcnow() - timedelta(minutes=10)
        with Session(sqlite_engine) as s, s.begin():
            assert queue.reap_stale(s, stale_after_s=60, backoff_base_s=0) == 1
        j = _job(sqlite_engine, jid)
        if attempt == 1:
            assert j.status == "queued" and "heartbeat" in j.error
            with Session(sqlite_engine) as s, s.begin():
                s.get(Job, jid).run_after = utcnow()
    assert _job(sqlite_engine, jid).status == "failed"


def test_heartbeat_ownership(sqlite_engine):
    jid = _enqueue(sqlite_engine, "test_echo")
    queue.claim(sqlite_engine, "w1")
    assert queue.heartbeat(sqlite_engine, jid, "w1")
    assert not queue.heartbeat(sqlite_engine, jid, "w2")


def test_timeout_fails_job_and_requests_restart(sqlite_engine):
    jid = _enqueue(sqlite_engine, "test_sleep", {"steps": 100})
    queue.claim(sqlite_engine, "w")
    with pytest.raises(WorkerMustExitError):
        run_claimed(sqlite_engine, jid, "w", get_settings(), threaded=True)
    j = _job(sqlite_engine, jid)
    assert j.status == "failed" and "exceeded" in j.error


def test_cancel_running_job_via_heartbeat(sqlite_engine, monkeypatch):
    monkeypatch.setattr(get_settings(), "job_heartbeat_s", 0.05)
    jid = _enqueue(sqlite_engine, "test_coop")
    queue.claim(sqlite_engine, "w")
    out: dict = {}
    t = threading.Thread(
        target=lambda: out.setdefault(
            "status", run_claimed(sqlite_engine, jid, "w", get_settings(), threaded=False)
        )
    )
    t.start()
    time.sleep(0.2)
    with Session(sqlite_engine) as s, s.begin():
        assert queue.cancel(s, s.get(Job, jid))
    t.join(10)
    assert out["status"] == "cancelled" and _job(sqlite_engine, jid).status == "cancelled"


def test_worker_loop_graceful_shutdown(sqlite_engine, monkeypatch):
    from strata.jobs.worker import Worker

    monkeypatch.setattr(get_settings(), "worker_poll_s", 0.05)
    ids = [_enqueue(sqlite_engine, "test_echo", {"x": i}) for i in range(5)]
    w = Worker(sqlite_engine, get_settings(), concurrency=2, maintenance_every_s=0.1)
    rc: dict = {}
    t = threading.Thread(target=lambda: rc.setdefault("rc", w.run_forever()))
    t.start()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if all(_job(sqlite_engine, i).status == "succeeded" for i in ids):
            break
        time.sleep(0.05)
    w.request_stop()
    t.join(20)
    assert rc["rc"] == 0
    assert [_job(sqlite_engine, i).result["echo"] for i in ids] == list(range(5))


def test_worker_cli_once(sqlite_engine):
    jid = _enqueue(sqlite_engine, "report", {"analysis_id": str(uuid.uuid4())})
    env = {**os.environ}
    r = subprocess.run(
        [sys.executable, "-m", "strata.jobs.worker", "--once"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    j = _job(sqlite_engine, jid)
    assert j.status == "failed" and "analysis not found" in j.error
