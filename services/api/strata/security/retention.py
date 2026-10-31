"""Retention: purge expired guest workspaces and expired rows (crypto-shredding datasets).

In Postgres deployments `pg_cron` runs the equivalent SQL (supabase/migrations/0004_retention.sql);
this Python path is used by the worker loop (all backends) and for SQLite dev databases.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from strata.db.models import Analysis, ChatSession, Dataset, ModelComparison, User
from strata.db.types import utcnow
from strata.security.vault import DatasetVault

log = logging.getLogger("strata.retention")


def purge_expired(session: Session, vault: DatasetVault, now: datetime | None = None) -> dict:
    now = now or utcnow()
    counts = {"datasets": 0, "analyses": 0, "chat_sessions": 0, "comparisons": 0, "guests": 0}
    expired_guests = select(User.id).where(User.is_guest.is_(True), User.expires_at < now)
    for ds in session.scalars(
        select(Dataset).where(or_(Dataset.expires_at < now, Dataset.owner_id.in_(expired_guests)))
    ):
        vault.shred(session, ds)
        counts["datasets"] += 1
    for model, key in (
        (Analysis, "analyses"),
        (ChatSession, "chat_sessions"),
        (ModelComparison, "comparisons"),
    ):
        for row in session.scalars(select(model).where(model.expires_at < now)):
            session.delete(row)
            counts[key] += 1
    for user in session.scalars(select(User).where(User.is_guest.is_(True), User.expires_at < now)):
        session.delete(user)  # ON DELETE CASCADE removes jobs, analyses, chats
        counts["guests"] += 1
    session.flush()
    if any(counts.values()):
        log.info("retention purge: %s", counts)
    return counts
