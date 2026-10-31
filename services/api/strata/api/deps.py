"""FastAPI dependencies: settings, DB session, authenticated principal, rate limits."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from strata.api.errors import ApiError
from strata.config import Settings, get_settings
from strata.db.models import User
from strata.db.session import get_sessionmaker
from strata.db.types import utcnow
from strata.security.auth import AuthError, Principal, authenticate_bearer
from strata.security.ratelimit import TokenBucketLimiter


def settings_dep() -> Settings:
    return get_settings()


def db_session() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SettingsDep = Annotated[Settings, Depends(settings_dep)]
DbDep = Annotated[Session, Depends(db_session)]


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_proxy_headers:
        for h in ("cf-connecting-ip", "x-real-ip"):
            if v := request.headers.get(h):
                return v.strip()
        if v := request.headers.get("x-forwarded-for"):
            return v.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if not auth:
        return None
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(
            401,
            "malformed Authorization header",
            "unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def current_principal(request: Request, db: DbDep, settings: SettingsDep) -> Principal:
    token = _bearer(request)
    if token is None:
        raise ApiError(
            401,
            "authentication required (guest token or Supabase session)",
            "unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        principal = authenticate_bearer(token, settings)
    except AuthError as exc:
        raise ApiError(
            401,
            str(exc),
            "unauthorized",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc
    user = db.get(User, principal.user_id)
    now = utcnow()
    if principal.is_guest:
        # Guest workspaces exist only server side; a valid signature for a purged guest is void.
        if user is None or not user.is_guest or (user.expires_at and user.expires_at < now):
            raise ApiError(401, "guest workspace expired", "unauthorized")
    elif user is None:
        user = User(id=principal.user_id, email=principal.email, is_guest=False)
        db.add(user)
        db.flush()
    elif user.is_guest:
        raise ApiError(401, "token subject mismatch", "unauthorized")
    if (now - user.last_seen_at).total_seconds() > 300:
        user.last_seen_at = now
    request.state.principal = principal
    return principal


PrincipalDep = Annotated[Principal, Depends(current_principal)]


def owner_expiry(db: Session, principal: Principal) -> datetime | None:
    """Rows owned by guests expire with the guest workspace."""
    if not principal.is_guest:
        return None
    user = db.get(User, principal.user_id)
    return user.expires_at if user else datetime.now(UTC)


# ------------------------------------------------------------------ rate limiting


@lru_cache(maxsize=1)
def _limiters() -> dict[str, TokenBucketLimiter]:
    s = get_settings()
    return {
        "default": TokenBucketLimiter(s.rate_limit_per_minute, s.rate_limit_burst),
        "expensive": TokenBucketLimiter(
            s.rate_limit_expensive_per_minute, max(1, s.rate_limit_expensive_per_minute // 2)
        ),
        "guest": TokenBucketLimiter(10, 5),
    }


def reset_rate_limits() -> None:
    _limiters.cache_clear()


def _limit(bucket: str, key: str) -> None:
    ok, retry = _limiters()[bucket].acquire(key)
    if not ok:
        raise ApiError(
            429,
            "rate limit exceeded",
            "rate_limited",
            headers={"Retry-After": str(max(1, int(retry + 0.999)))},
        )


def rate_limit_default(request: Request, settings: SettingsDep) -> None:
    _limit("default", client_ip(request, settings))


def rate_limit_expensive(principal: PrincipalDep) -> None:
    _limit("expensive", str(principal.user_id))


def rate_limit_guest_issue(request: Request, settings: SettingsDep) -> None:
    _limit("guest", client_ip(request, settings))
