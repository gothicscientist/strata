from __future__ import annotations

import gzip
import io
import logging
import zipfile

import pytest

from strata.security.logging import REDACTED, GenotypeRedactionFilter, looks_like_genotypes
from strata.security.ratelimit import TokenBucketLimiter
from strata.security.uploads import UploadRejectedError, sanitize_filename, validate_upload


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\genome.txt", "genome.txt"),
        ("my genome (1).txt", "my genome _1_.txt"),
        ("\x00\x1b[31mevil.txt", "_31mevil.txt"),
        ("", "upload"),
        ("....", "upload"),
        ("a" * 300 + ".txt", "a" * 116 + ".txt"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_validate_upload_decompresses_and_limits():
    body = b"rs1\t1\t100\tAG\n" * 100
    assert validate_upload("g.txt.gz", gzip.compress(body), max_bytes=10**6).data == body
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", body)
        zf.writestr("b.txt", body)
    with pytest.raises(UploadRejectedError):
        validate_upload("g.zip", buf.getvalue(), max_bytes=10**6)
    with pytest.raises(UploadRejectedError) as e:
        validate_upload("g.txt", body, max_bytes=10)
    assert e.value.status_code == 413
    with pytest.raises(UploadRejectedError):
        validate_upload("g.txt", b"", max_bytes=10)
    with pytest.raises(UploadRejectedError) as e:
        validate_upload("g.pdf", body, max_bytes=10**6)
    assert e.value.status_code == 415


def test_gzip_bomb_rejected(monkeypatch):
    import strata.security.uploads as up

    monkeypatch.setattr(up, "MAX_DECOMPRESSED_BYTES", 10_000)
    bomb = gzip.compress(b"0" * 1_000_000)
    with pytest.raises(UploadRejectedError) as e:
        validate_upload("x.txt.gz", bomb, max_bytes=10**6)
    assert e.value.status_code == 413


@pytest.mark.parametrize(
    "text",
    [
        "rs3131972\t1\t752721\tAG",
        "parsed row rs12184325,1,754105,CC ok",
        "genotype rs548049170: TT",
        "1\t69869\trs548049170\tT\tC\t.\tPASS\t.\tGT\t0/1",
        "calls " + " ".join(["AG", "TT", "CC", "GG"] * 4),
        "dosage [" + ", ".join(["0", "1", "2"] * 20) + "]",
    ],
)
def test_genotype_like_detected(text):
    assert looks_like_genotypes(text)


@pytest.mark.parametrize(
    "text",
    [
        "job 1234 succeeded in 2.5s",
        "uploaded dataset 3f2c9a7e-0000-4000-8000-000000000000 (raw_dna, 612 KB)",
        "GET /api/v1/reference/populations?q=rs123 200",
        "weights [0.61, 0.39]",
    ],
)
def test_ordinary_logs_pass(text):
    assert not looks_like_genotypes(text)


def test_filter_redacts_record(caplog):
    log = logging.getLogger("strata.test.redact")
    log.addFilter(GenotypeRedactionFilter())
    with caplog.at_level(logging.INFO, logger="strata.test.redact"):
        log.info("bad row %s", "rs3131972\t1\t752721\tAG")
        log.info("fine %d", 3)
    assert caplog.records[0].getMessage() == REDACTED
    assert "rs3131972" not in caplog.text
    assert caplog.records[1].getMessage() == "fine 3"


def test_token_bucket():
    t = [0.0]
    lim = TokenBucketLimiter(60, 3, clock=lambda: t[0])
    assert [lim.acquire("k")[0] for _ in range(4)] == [True, True, True, False]
    ok, retry = lim.acquire("k")
    assert not ok and 0 < retry <= 1.0
    assert lim.acquire("other")[0]
    t[0] += 1.0
    assert lim.acquire("k")[0]


def test_security_headers_and_cors(monkeypatch, tmp_path):
    from api.support import env_for, reset_platform_caches
    from fastapi.testclient import TestClient

    for k, v in env_for(
        tmp_path, None, STRATA_CORS_ORIGINS="http://localhost:3000,https://strata.pages.dev"
    ).items():
        monkeypatch.setenv(k, v)
    reset_platform_caches()
    from strata.api.main import create_app

    with TestClient(create_app()) as c:
        r = c.options(
            "/api/v1/datasets",
            headers={
                "Origin": "https://strata.pages.dev",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert r.headers["access-control-allow-origin"] == "https://strata.pages.dev"
        r = c.get("/api/v1/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in r.headers
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["cache-control"] == "no-store"
        assert "max-age" in r.headers["strict-transport-security"]
        # Validation errors never echo submitted values.
        g = c.post("/api/v1/auth/guest").json()["token"]
        r = c.post(
            "/api/v1/analyses",
            headers={"Authorization": f"Bearer {g}"},
            json={"kind": "rs3131972 AG", "params": {}},
        )
        assert r.status_code == 422 and "rs3131972" not in r.text
    reset_platform_caches()
