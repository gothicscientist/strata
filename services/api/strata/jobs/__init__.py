"""Job queue: Postgres (FOR UPDATE SKIP LOCKED) with a SQLite fallback, plus inline mode."""

from strata.jobs.queue import PermanentJobError, enqueue
from strata.jobs.registry import JobContext, kinds, register
from strata.jobs.runner import run_inline, submit

__all__ = [
    "JobContext", "PermanentJobError", "enqueue", "kinds", "register", "run_inline", "submit",
]
