from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from strata.security.auth import (
    AuthError,
    issue_guest_token,
    verify_guest_token,
    verify_supabase_jwt,
)

SECRET = "super-secret-jwt-token-with-at-least-32-characters"


def _claims(**over):
    now = int(time.time())
    c = {
        "sub": str(uuid.uuid4()),
        "aud": "authenticated",
        "role": "authenticated",
        "email": "a@example.org",
        "iat": now,
        "exp": now + 3600,
    }
    c.update(over)
    return c


class StaticJWKS:
    """Resolves the signing key locally (stands in for the network JWKS fetch)."""

    def __init__(self, key):
        self.key = key

    def signing_key(self, token):
        return self.key


def test_hs256_valid_and_invalid():
    c = _claims()
    tok = jwt.encode(c, SECRET, algorithm="HS256")
    p = verify_supabase_jwt(tok, hs256_secret=SECRET, jwks_url=None)
    assert str(p.user_id) == c["sub"] and p.kind == "user" and p.email == "a@example.org"
    with pytest.raises(AuthError):
        verify_supabase_jwt(
            jwt.encode(c, "wrong" * 10, algorithm="HS256"), hs256_secret=SECRET, jwks_url=None
        )
    with pytest.raises(AuthError):  # expired beyond leeway
        verify_supabase_jwt(
            jwt.encode(_claims(exp=int(time.time()) - 120), SECRET),
            hs256_secret=SECRET,
            jwks_url=None,
        )
    with pytest.raises(AuthError):  # wrong audience
        verify_supabase_jwt(
            jwt.encode(_claims(aud="other"), SECRET), hs256_secret=SECRET, jwks_url=None
        )
    with pytest.raises(AuthError):  # anon key is not a session
        verify_supabase_jwt(
            jwt.encode(_claims(role="anon"), SECRET), hs256_secret=SECRET, jwks_url=None
        )
    with pytest.raises(AuthError):  # sub must be a UUID
        verify_supabase_jwt(
            jwt.encode(_claims(sub="x"), SECRET), hs256_secret=SECRET, jwks_url=None
        )


def test_issuer_checked():
    tok = jwt.encode(_claims(iss="https://evil.example/auth/v1"), SECRET)
    with pytest.raises(AuthError):
        verify_supabase_jwt(
            tok, hs256_secret=SECRET, jwks_url=None, issuer="https://proj.supabase.co/auth/v1"
        )


@pytest.mark.parametrize("alg", ["RS256", "ES256"])
def test_asymmetric_jwks(alg):
    priv = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if alg == "RS256"
        else ec.generate_private_key(ec.SECP256R1())
    )
    tok = jwt.encode(_claims(), priv, algorithm=alg, headers={"kid": "k1"})
    p = verify_supabase_jwt(
        tok, hs256_secret=None, jwks_url="unused", jwks=StaticJWKS(priv.public_key())
    )
    assert p.kind == "user"
    other = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if alg == "RS256"
        else ec.generate_private_key(ec.SECP256R1())
    )
    with pytest.raises(AuthError):
        verify_supabase_jwt(
            tok, hs256_secret=None, jwks_url="unused", jwks=StaticJWKS(other.public_key())
        )


def test_alg_none_and_unconfigured_rejected():
    tok = jwt.encode(_claims(), None, algorithm="none")
    with pytest.raises(AuthError):
        verify_supabase_jwt(tok, hs256_secret=SECRET, jwks_url=None)
    with pytest.raises(AuthError):
        verify_supabase_jwt(jwt.encode(_claims(), SECRET), hs256_secret=None, jwks_url=None)


def test_guest_tokens():
    secret = b"k" * 32
    uid = uuid.uuid4()
    tok, exp = issue_guest_token(uid, secret=secret, ttl=timedelta(hours=24))
    p = verify_guest_token(tok, secret=secret)
    assert p.user_id == uid and p.is_guest and abs((p.expires_at - exp).total_seconds()) < 1
    with pytest.raises(AuthError):
        verify_guest_token(tok, secret=b"x" * 32)
    old, _ = issue_guest_token(
        uid, secret=secret, ttl=timedelta(hours=1), now=datetime.now(UTC) - timedelta(hours=2)
    )
    with pytest.raises(AuthError):
        verify_guest_token(old, secret=secret)
    # A Supabase-style token signed with the guest secret is not a guest token.
    with pytest.raises(AuthError):
        verify_guest_token(jwt.encode(_claims(), secret), secret=secret)


def test_api_accepts_supabase_user(monkeypatch, tmp_path):
    from api.support import env_for, reset_platform_caches
    from fastapi.testclient import TestClient

    for k, v in env_for(tmp_path, None, SUPABASE_JWT_SECRET=SECRET).items():
        monkeypatch.setenv(k, v)
    reset_platform_caches()
    from strata.api.main import create_app

    c = _claims()
    with TestClient(create_app()) as client:
        h = {"Authorization": f"Bearer {jwt.encode(c, SECRET)}"}
        me = client.get("/api/v1/auth/me", headers=h).json()
        assert me["id"] == c["sub"] and me["kind"] == "user" and me["expires_at"]
        assert client.get("/api/v1/datasets", headers=h).json() == []
        # A forged guest token for that user id is rejected (guest secret differs, and the
        # profile is not a guest).
        fake, _ = issue_guest_token(uuid.UUID(c["sub"]), secret=b"x" * 32, ttl=timedelta(hours=1))
        r = client.get("/api/v1/datasets", headers={"Authorization": f"Bearer {fake}"})
        assert r.status_code == 401
    reset_platform_caches()
