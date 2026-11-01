from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends

from strata.api.deps import DbDep, PrincipalDep, SettingsDep, rate_limit_guest_issue
from strata.api.schemas import GuestToken, Me
from strata.db.models import User
from strata.db.types import utcnow
from strata.security.auth import issue_guest_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/guest",
    response_model=GuestToken,
    status_code=201,
    dependencies=[Depends(rate_limit_guest_issue)],
    summary="Create a temporary guest workspace",
)
def create_guest(db: DbDep, settings: SettingsDep) -> GuestToken:
    """Issues a signed bearer token for a fresh guest workspace. Everything created in it
    (datasets, analyses, chats) is deleted when it expires (default 24 h)."""
    ttl = timedelta(hours=settings.guest_ttl_hours)
    uid = uuid.uuid4()
    token, exp = issue_guest_token(uid, secret=settings.guest_secret_bytes(), ttl=ttl, now=utcnow())
    db.add(User(id=uid, is_guest=True, expires_at=exp, display_name="guest"))
    return GuestToken(token=token, expires_at=exp, owner_id=uid)


@router.get("/me", response_model=Me, summary="Current principal")
def me(principal: PrincipalDep) -> Me:
    return Me(
        id=principal.user_id,
        kind=principal.kind,
        email=principal.email,
        expires_at=principal.expires_at,
    )
