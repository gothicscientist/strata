"""Queue worker: `python -m strata.jobs.worker [--once] [--kinds a,b] [--concurrency N]`.

Polls the jobs table, claims with FOR UPDATE SKIP LOCKED (Postgres), runs handlers with
heartbeats and timeouts, reaps jobs abandoned by crashed workers, and runs the retention purge.
SIGTERM/SIGINT trigger a graceful shutdown: no new claims, in-flight jobs finish (up to the
grace period), then the process exits.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import threading
import time
import uuid

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from strata.config import Settings, get_settings
from strata.db.session import get_engine
from strata.jobs import queue
from strata.jobs.runner import WorkerMustExitError, run_claimed
from strata.security.logging import install_log_redaction

log = logging.getLogger("strata.worker")
EXIT_RESTART = 3


class Worker:
    def __init__(self, engine: Engine, settings: Settings, *, kinds: list[str] | None = None,
                 concurrency: int = 1, maintenance_every_s: float = 60.0) -> None:
        self.engine = engine
        self.settings = settings
        self.kinds = kinds
        self.concurrency = max(1, concurrency)
        self.maintenance_every_s = maintenance_every_s
        self.id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.stopping = threading.Event()
        self.must_exit = threading.Event()
        self._last_maint = 0.0

    def request_stop(self, *_: object) -> None:
        if not self.stopping.is_set():
            log.info("worker %s: shutdown requested; finishing in-flight jobs", self.id)
        self.stopping.set()

    def maintenance(self) -> None:
        from strata.security.retention import purge_expired
        from strata.security.vault import vault_from_settings

        with Session(self.engine) as s, s.begin():
            n = queue.reap_stale(s, stale_after_s=self.settings.job_stale_after_s,
                                 backoff_base_s=self.settings.job_backoff_base_s)
            if n:
                log.warning("requeued %d stale job(s)", n)
        with Session(self.engine) as s, s.begin():
            purge_expired(s, vault_from_settings())

    def run_one(self) -> bool:
        """Claim and run at most one job. Returns True if a job was run."""
        job_id = queue.claim(self.engine, self.id, self.kinds)
        if job_id is None:
            return False
        try:
            run_claimed(self.engine, job_id, self.id, self.settings, threaded=True)
        except WorkerMustExitError:
            log.error("job %s overran its timeout; worker will exit for a clean restart", job_id)
            self.must_exit.set()
            self.stopping.set()
        return True

    def _loop(self) -> None:
        while not self.stopping.is_set():
            try:
                ran = self.run_one()
            except Exception:  # noqa: BLE001 - keep polling through transient DB errors
                log.exception("worker loop error")
                ran = False
            if not ran:
                self.stopping.wait(self.settings.worker_poll_s)

    def run_forever(self) -> int:
        log.info("worker %s started (concurrency=%d, kinds=%s)", self.id, self.concurrency,
                 self.kinds or "all")
        threads = [threading.Thread(target=self._loop, name=f"worker-{i}", daemon=True)
                   for i in range(self.concurrency)]
        for t in threads:
            t.start()
        while not self.stopping.is_set():
            now = time.monotonic()
            if now - self._last_maint >= self.maintenance_every_s:
                self._last_maint = now
                try:
                    self.maintenance()
                except Exception:  # noqa: BLE001
                    log.exception("maintenance failed")
            self.stopping.wait(1.0)
        grace = self.settings.job_timeout_s
        deadline = time.monotonic() + grace
        for t in threads:
            t.join(timeout=max(0.0, deadline - time.monotonic()))
        log.info("worker %s stopped", self.id)
        return EXIT_RESTART if self.must_exit.is_set() else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m strata.jobs.worker")
    p.add_argument("--once", action="store_true", help="run queued jobs until empty, then exit")
    p.add_argument("--kinds", default="", help="comma separated job kinds to accept")
    p.add_argument("--concurrency", type=int,
                   default=int(os.environ.get("STRATA_WORKER_CONCURRENCY", "1")))
    args = p.parse_args(argv)
    settings = get_settings()
    install_log_redaction(settings.log_level)
    engine = get_engine()
    if engine.dialect.name == "sqlite":
        from strata.db.session import init_db

        init_db(engine)
    kinds = [k for k in args.kinds.split(",") if k] or None
    worker = Worker(engine, settings, kinds=kinds, concurrency=args.concurrency)
    if args.once:
        worker.maintenance()
        while worker.run_one() and not worker.must_exit.is_set():
            pass
        return EXIT_RESTART if worker.must_exit.is_set() else 0
    signal.signal(signal.SIGTERM, worker.request_stop)
    signal.signal(signal.SIGINT, worker.request_stop)
    return worker.run_forever()


if __name__ == "__main__":
    sys.exit(main())
