"""Applies supabase/migrations to a scratch Postgres database and checks RLS isolation.
Needs STRATA_TEST_POSTGRES_URL (a superuser connection); pgvector is optional."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).resolve().parents[4] / "supabase" / "migrations"


@pytest.fixture
def conn():
    url = os.environ.get("STRATA_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("STRATA_TEST_POSTGRES_URL not set")
    import psycopg

    dsn = url.replace("postgresql+psycopg://", "postgresql://")
    name = f"strata_rls_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f"create database {name}")
    test_dsn = dsn.replace("/strata_test", f"/{name}", 1)
    c = psycopg.connect(test_dsn, autocommit=True)
    try:
        has_vector = bool(
            c.execute("select 1 from pg_available_extensions where name = 'vector'").fetchone()
        )
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if "knowledge" in f.name and not has_vector:
                continue
            c.execute(f.read_text())
        yield c
    finally:
        c.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f"drop database {name} with (force)")


def test_rls_isolates_owners(conn):
    import psycopg

    a, b = uuid.uuid4(), uuid.uuid4()
    conn.execute("insert into profiles(id) values (%s), (%s)", (a, b))
    for owner, name in ((a, "mine"), (b, "theirs")):
        conn.execute(
            "insert into datasets(owner_id,name,kind,input_sha256,payload_sha256,payload_format,"
            "nonce,ciphertext) values (%s,%s,'g25','x','y','g25-json-v1','\\x00','\\x01')",
            (owner, name),
        )
    conn.execute(
        "insert into dataset_keys(dataset_id, owner_id, wrapped_key, kek_id) "
        "select id, owner_id, '\\x01', 'k' from datasets"
    )
    with conn.transaction(force_rollback=True):
        conn.execute("set local role authenticated")
        conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (str(a),))
        rows = conn.execute("select name from datasets").fetchall()
        assert rows == [("mine",)]
        assert conn.execute("delete from datasets where owner_id = %s", (b,)).rowcount == 0
    for stmt in ("select ciphertext from datasets", "select * from dataset_keys"):
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            conn.transaction(force_rollback=True),
        ):
            conn.execute("set local role authenticated")
            conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (str(a),))
            conn.execute(stmt)


def test_purge_shreds_expired_guest(conn):
    g = uuid.uuid4()
    conn.execute(
        "insert into profiles(id, is_guest, expires_at) "
        "values (%s, true, now() - interval '1 hour')",
        (g,),
    )
    conn.execute(
        "insert into datasets(owner_id,name,kind,input_sha256,payload_sha256,payload_format,"
        "nonce,ciphertext) values (%s,'g','g25','x','y','g25-json-v1','\\x00','\\x01')",
        (g,),
    )
    conn.execute(
        "insert into dataset_keys(dataset_id, owner_id, wrapped_key, kek_id) "
        "select id, owner_id, '\\x01', 'k' from datasets"
    )
    out = conn.execute("select public.purge_expired_data()").fetchone()[0]
    assert out["dataset_keys"] == 1 and out["datasets"] == 1 and out["guests"] == 1
    assert conn.execute("select count(*) from dataset_keys").fetchone()[0] == 0
