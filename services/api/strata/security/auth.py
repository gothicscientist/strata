"""Authentication: Supabase-issued JWTs (HS256 secret or RS256/ES256 via JWKS) and Strata
guest tokens (HS256, signed with a server secret, short-lived guest workspaces)."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from jwt import PyJWKClient

GUEST_ISSUER = "strata-guest"
GUEST_AUDIENCE = "strata-api"


class AuthError(Exception):
    """Token missing, malformed, expired, or not verifiable."""


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    kind: Literal["user", "guest"]
    email: str | None = None
    expires_at: datetime | None = None
    role: str | None = None

    @property
    def is_guest(self) -> bool:
        return self.kind == "guest"


# ---------------------------------------------------------------- guest tokens


def issue_guest_token(
    user_id: uuid.UUID, *, secret: bytes, ttl: timedelta, now: datetime | None = None
) -> tuple[str, datetime]:
    now = now or datetime.now(UTC)
    exp = now + ttl
    claims = {
        "iss": GUEST_ISSUER,
        "aud": GUEST_AUDIENCE,
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": uuid.uuid4().hex,
        "typ": "guest",
    }
    return jwt.encode(claims, secret, algorithm="HS256"), exp


def verify_guest_token(token: str, *, secret: bytes) -> Principal:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=GUEST_AUDIENCE,
            issuer=GUEST_ISSUER,
            options={"require": ["exp", "sub", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"invalid guest token: {exc}") from exc
    if claims.get("typ") != "guest":
        raise AuthError("not a guest token")
    return Principal(
        user_id=_parse_uuid(claims["sub"]),
        kind="guest",
        expires_at=datetime.fromtimestamp(claims["exp"], UTC),
    )


# ---------------------------------------------------------------- Supabase JWTs


class JWKSCache:
    """Thread-safe JWKS fetcher with a TTL (PyJWKClient caches keys; we bound staleness)."""

    def __init__(self, url: str, ttl_s: int = 600) -> None:
        self._client = PyJWKClient(url, cache_keys=True, lifespan=ttl_s, timeout=5)
        self._lock = threading.Lock()

    def signing_key(self, token: str) -> Any:
        with self._lock:
            try:
                return self._client.get_signing_key_from_jwt(token).key
            except jwt.PyJWKClientError as exc:
                raise AuthError(f"cannot resolve signing key: {exc}") from exc


_jwks_caches: dict[str, JWKSCache] = {}
_jwks_lock = threading.Lock()


def _jwks_for(url: str) -> JWKSCache:
    with _jwks_lock:
        if url not in _jwks_caches:
            _jwks_caches[url] = JWKSCache(url)
        return _jwks_caches[url]


def verify_supabase_jwt(
    token: str,
    *,
    hs256_secret: str | None,
    jwks_url: str | None,
    audience: str = "authenticated",
    issuer: str | None = None,
    jwks: JWKSCache | None = None,
    leeway_s: int = 30,
) -> Principal:
    """Verify a Supabase access token. Asymmetric (RS256/ES256) tokens are checked against the
    project JWKS; legacy HS256 tokens against the project JWT secret. The algorithm list is
    pinned per key type so an attacker cannot downgrade to HS256 using the public key."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError(f"malformed token: {exc}") from exc
    alg = header.get("alg")
    opts = {"require": ["exp", "sub"]}
    try:
        if alg == "HS256":
            if not hs256_secret:
                raise AuthError("HS256 token but SUPABASE_JWT_SECRET is not configured")
            claims = jwt.decode(
                token, hs256_secret, algorithms=["HS256"], audience=audience,
                issuer=issuer, options=opts, leeway=leeway_s,
            )
        elif alg in ("RS256", "ES256"):
            cache = jwks or (_jwks_for(jwks_url) if jwks_url else None)
            if cache is None:
                raise AuthError("asymmetric token but SUPABASE_JWKS_URL is not configured")
            key = cache.signing_key(token)
            claims = jwt.decode(
                token, key, algorithms=[alg], audience=audience,
                issuer=issuer, options=opts, leeway=leeway_s,
            )
        else:
            raise AuthError(f"unsupported token algorithm {alg!r}")
    except jwt.PyJWTError as exc:
        raise AuthError(f"invalid token: {exc}") from exc
    if claims.get("role") == "anon":
        raise AuthError("anonymous Supabase key is not a user session")
    return Principal(
        user_id=_parse_uuid(claims["sub"]),
        kind="user",
        email=claims.get("email"),
        expires_at=datetime.fromtimestamp(claims["exp"], UTC),
        role=claims.get("role"),
    )


def authenticate_bearer(token: str, settings: Any) -> Principal:
    """Route a bearer token to the right verifier based on its (unverified) issuer."""
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise AuthError(f"malformed token: {exc}") from exc
    if unverified.get("iss") == GUEST_ISSUER:
        return verify_guest_token(token, secret=settings.guest_secret_bytes())
    jwks_url = settings.supabase_jwks_url
    if not jwks_url and settings.supabase_url:
        jwks_url = settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
    issuer = settings.supabase_url.rstrip("/") + "/auth/v1" if settings.supabase_url else None
    if not (settings.supabase_jwt_secret or jwks_url):
        raise AuthError("user tokens are not accepted: Supabase auth is not configured")
    return verify_supabase_jwt(
        token,
        hs256_secret=settings.supabase_jwt_secret,
        jwks_url=jwks_url,
        audience=settings.supabase_jwt_audience,
        issuer=issuer,
    )


def _parse_uuid(sub: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(sub))
    except ValueError as exc:
        raise AuthError("token subject is not a UUID") from exc
