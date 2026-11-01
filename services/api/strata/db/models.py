"""SQLAlchemy 2.0 typed ORM models. Mirrored by supabase/migrations/*.sql (Postgres + RLS)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from strata.db.types import JSONType, UTCDateTime, utcnow


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONType, list[Any]: JSONType, datetime: UTCDateTime}


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    """Application profile. For Supabase users `id` equals `auth.users.id` (JWT `sub`)."""

    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Guests only: everything owned by an expired guest is purged by the retention job.
    expires_at: Mapped[datetime | None] = mapped_column()


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (Index("ix_datasets_owner_created", "owner_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))  # g25 | raw_dna | vcf
    original_filename: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # sha256 of the uploaded bytes (provenance; not reversible to genotypes).
    input_sha256: Mapped[str] = mapped_column(String(64))
    # sha256 of the plaintext payload that was encrypted (integrity / provenance).
    payload_sha256: Mapped[str] = mapped_column(String(64))
    payload_format: Mapped[str] = mapped_column(String(32))
    qc_report: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Non-sensitive descriptors safe to return to clients and the agent.
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Encrypted payload: inline (storage_backend=db) or an object path in local/Supabase storage.
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    storage_path: Mapped[str | None] = mapped_column(String(512))
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    panel_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(index=True)

    key: Mapped[DatasetKey | None] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", uselist=False
    )


class DatasetKey(Base):
    """Wrapped per-dataset data key, kept apart from the ciphertext so deletion shreds it."""

    __tablename__ = "dataset_keys"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    kek_id: Mapped[str] = mapped_column(String(32))
    algorithm: Mapped[str] = mapped_column(String(32), default="AES-256-GCM")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="key")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "run_after", "priority"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=100)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    timeout_s: Mapped[int | None] = mapped_column(Integer)
    run_after: Mapped[datetime] = mapped_column(default=utcnow)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    heartbeat_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_owner_created", "owner_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(200))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    dataset_ids: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    result: Mapped[dict[str, Any] | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    # code version, reference version, seed, input hashes, software versions, timings.
    provenance: Mapped[dict[str, Any]] = mapped_column(default=dict)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column()
    expires_at: Mapped[datetime | None] = mapped_column(index=True)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(200))
    dataset_ids: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(index=True)

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.seq",
    )


class ChatMessage(Base):
    """One chat turn. Assistant turns keep the full tool audit trail."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list[Any]] = mapped_column(default=list)
    tool_results: Mapped[list[Any]] = mapped_column(default=list)
    grounding: Mapped[dict[str, Any] | None] = mapped_column()
    citations: Mapped[list[Any]] = mapped_column(default=list)
    usage: Mapped[dict[str, Any] | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class ModelComparison(Base):
    """A saved side-by-side comparison of analyses (e.g. G25 fit vs qpAdm model)."""

    __tablename__ = "model_comparisons"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    analysis_ids: Mapped[list[Any]] = mapped_column(default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(index=True)
