"""Job kind -> handler registry."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from strata.config import Settings


class JobCancelledError(Exception):
    pass


@dataclass
class JobContext:
    job_id: uuid.UUID
    kind: str
    owner_id: uuid.UUID | None
    payload: dict[str, Any]
    session: Session
    settings: Settings
    attempt: int = 1
    deadline: float | None = None
    _cancelled: bool = field(default=False, repr=False)
    progress: float | None = None

    def check(self) -> None:
        """Handlers call this between expensive steps to honour cancellation / timeouts."""
        if self._cancelled:
            raise JobCancelledError(str(self.job_id))
        if self.deadline is not None and time.monotonic() > self.deadline:
            from strata.jobs.queue import JobTimeoutError

            raise JobTimeoutError("job exceeded its time limit")

    def cancel(self) -> None:
        self._cancelled = True


Handler = Callable[[JobContext], dict[str, Any]]


@dataclass(frozen=True)
class JobSpec:
    kind: str
    handler: Handler
    timeout_s: int
    description: str


_REGISTRY: dict[str, JobSpec] = {}


def register(
    kind: str, *, timeout_s: int = 600, description: str = ""
) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _REGISTRY[kind] = JobSpec(kind, fn, timeout_s, description or (fn.__doc__ or "").strip())
        return fn

    return deco


_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        import strata.jobs.handlers  # noqa: F401 - registers built-in handlers

        _loaded = True


def get_spec(kind: str) -> JobSpec:
    _ensure_loaded()
    try:
        return _REGISTRY[kind]
    except KeyError:
        raise ValueError(f"unknown job kind {kind!r}") from None


def get_handler(kind: str) -> Handler:
    return get_spec(kind).handler


def kinds() -> list[str]:
    _ensure_loaded()
    return sorted(_REGISTRY)
