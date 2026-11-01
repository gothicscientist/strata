"""Engine / session factory. SQLite (dev, tests) and Postgres (prod) share one code path."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from strata.config import get_settings


def make_engine(url: str, *, echo: bool = False) -> Engine:
    kwargs: dict[str, Any] = {"echo": echo, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
    else:
        kwargs.update(pool_pre_ping=True, pool_size=3, max_overflow=2, pool_recycle=300)
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn: Any, _rec: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            if url not in ("sqlite://", "sqlite:///:memory:"):
                cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    s = get_settings()
    return make_engine(s.database_url, echo=s.db_echo)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def reset_engine_cache() -> None:
    with contextlib.suppress(Exception):
        get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Engine | None = None) -> None:
    """Create tables (SQLite/dev). Postgres production schema comes from supabase/migrations."""
    from strata.db.models import Base

    Base.metadata.create_all(engine or get_engine())
