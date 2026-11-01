from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from api.support import env_for, reset_platform_caches
from sqlalchemy import Engine


@pytest.fixture
def sqlite_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Engine]:
    for k, v in env_for(tmp_path, None).items():
        monkeypatch.setenv(k, v)
    reset_platform_caches()
    from strata.db.session import get_engine, init_db

    eng = get_engine()
    init_db(eng)
    yield eng
    reset_platform_caches()


@pytest.fixture
def pg_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Engine]:
    """Real Postgres (set STRATA_TEST_POSTGRES_URL, e.g. postgresql+psycopg://...)."""
    url = os.environ.get("STRATA_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("STRATA_TEST_POSTGRES_URL not set")
    for k, v in env_for(tmp_path, None, DATABASE_URL=url).items():
        monkeypatch.setenv(k, v)
    reset_platform_caches()
    from sqlalchemy import text

    from strata.db.models import Base
    from strata.db.session import get_engine

    eng = get_engine()
    with eng.begin() as c:
        c.execute(text("drop schema if exists strata_test cascade"))
        c.execute(text("create schema strata_test"))
    eng.dispose()
    from strata.db.session import make_engine

    eng = make_engine(url)

    from sqlalchemy import event

    @event.listens_for(eng, "connect")
    def _path(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("set search_path to strata_test")
        cur.close()

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()
    reset_platform_caches()
