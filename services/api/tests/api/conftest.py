from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.support import build_synthetic_reference, env_for, reset_platform_caches


@pytest.fixture(scope="session")
def synthetic_derived(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_synthetic_reference(tmp_path_factory.mktemp("derived"))


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, derived: Path | None,
            **extra: str) -> Iterator[TestClient]:
    for k, v in env_for(tmp_path, derived, **extra).items():
        monkeypatch.setenv(k, v)
    reset_platform_caches()
    from strata.api.main import create_app

    with TestClient(create_app()) as c:
        yield c
    reset_platform_caches()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    """API without reference data (capabilities honestly report it missing)."""
    yield from _client(monkeypatch, tmp_path, None)


@pytest.fixture
def ref_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
               synthetic_derived: Path) -> Iterator[TestClient]:
    """API with the SYNTHETIC reference library installed."""
    yield from _client(monkeypatch, tmp_path, synthetic_derived)


def guest(c: TestClient) -> dict[str, str]:
    r = c.post("/api/v1/auth/guest")
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def make_guest():
    return guest
