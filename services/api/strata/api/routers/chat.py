"""Research assistant chat. Messages stream as Server-Sent Events whose `event:` name equals
the event `type`: text_delta, tool_call, tool_result, message_done, error, saved, done.
Every tool call and tool result is persisted with the assistant message for audit."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from strata.api import datasets as dsvc
from strata.api.deps import DbDep, PrincipalDep, SettingsDep, owner_expiry, rate_limit_expensive
from strata.api.errors import ApiError, not_found
from strata.api.schemas import (
    ChatMessageCreate,
    ChatMessageOut,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionOut,
)
from strata.config import Settings
from strata.db.models import ChatMessage, ChatSession, Dataset, Job
from strata.db.session import get_sessionmaker
from strata.db.types import utcnow
from strata.jobs import queue
from strata.jobs.runner import submit
from strata.security.auth import Principal
from strata.security.vault import vault_from_settings

log = logging.getLogger("strata.chat")
router = APIRouter(prefix="/chat", tags=["chat"])
HISTORY_TURNS = 20


def _owned(db: Session, principal: Principal, sid: uuid.UUID) -> ChatSession:
    s = db.get(ChatSession, sid)
    if s is None or s.owner_id != principal.user_id:
        raise not_found("chat session")
    return s


@router.post(
    "/sessions",
    response_model=ChatSessionOut,
    status_code=201,
    summary="Start a research-assistant session",
)
def create_session(body: ChatSessionCreate, db: DbDep, principal: PrincipalDep) -> ChatSession:
    for did in body.dataset_ids:
        dsvc.get_owned(db, principal, did)
    s = ChatSession(
        owner_id=principal.user_id,
        title=body.title,
        dataset_ids=[str(d) for d in body.dataset_ids],
        expires_at=owner_expiry(db, principal),
    )
    db.add(s)
    db.flush()
    return s


@router.get("/sessions", response_model=list[ChatSessionOut], summary="List my sessions")
def list_sessions(db: DbDep, principal: PrincipalDep) -> list[ChatSession]:
    return list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.owner_id == principal.user_id)
            .order_by(ChatSession.updated_at.desc())
        )
    )


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetail,
    summary="Session with full message + tool audit history",
)
def get_session(session_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> ChatSession:
    return _owned(db, principal, session_id)


@router.delete("/sessions/{session_id}", status_code=204, summary="Delete a session")
def delete_session(session_id: uuid.UUID, db: DbDep, principal: PrincipalDep) -> Response:
    db.delete(_owned(db, principal, session_id))
    return Response(status_code=204)


# ------------------------------------------------------------------ platform hooks for tools


def _list_datasets(owner: uuid.UUID) -> list[dict[str, Any]]:
    with get_sessionmaker()() as s:
        rows = s.scalars(select(Dataset).where(Dataset.owner_id == owner)).all()
        # Metadata only: no payloads, no genotypes.
        return [
            {
                "id": str(d.id),
                "kind": d.kind,
                "name": d.name,
                "created_at": d.created_at.isoformat(),
                "space": d.summary.get("space"),
                "sample_names": d.summary.get("sample_names", []),
                "qc": {
                    k: d.qc_report.get(k)
                    for k in (
                        "n_variants",
                        "call_rate",
                        "panel_overlap",
                        "n_samples",
                        "n_dims",
                        "scaled",
                        "vendor",
                        "build",
                    )
                    if k in d.qc_report
                },
            }
            for d in rows
        ]


def _dataset_coordinates(
    owner: uuid.UUID, dataset_id: str, space: str, target: str | None = None
) -> dict[str, Any] | None:
    """Derived coordinates only (G25 rows or a PCA projection), owner-checked."""
    from strata.jobs.handlers import project_dataset

    try:
        did = uuid.UUID(str(dataset_id))
    except ValueError:
        return None
    with get_sessionmaker()() as s:
        ds = s.get(Dataset, did)
        if ds is None or ds.owner_id != owner:
            return None
        payload = dsvc.open_payload(s, vault_from_settings(), ds)
        if payload.format == "g25-json-v1":
            if space != dsvc.G25_SPACE:
                return None
            names = payload.meta["names"]
            name = target if target in names else names[0]
            return {
                "space": space,
                "name": name,
                "coords": [float(x) for x in payload.arrays["matrix"][names.index(name)]],
            }
        proj = project_dataset(payload, space)
        if proj is None:
            return None
        return {
            "space": space,
            "name": ds.name,
            "coords": proj["coords"],
            "n_snps_used": proj.get("n_snps_used"),
        }


def _make_run_job(owner: uuid.UUID, settings: Settings):
    def run_job(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        with get_sessionmaker()() as s:
            job = submit(
                s, kind, {"params": payload}, owner_id=owner, settings=settings, priority=50
            )
            deadline = time.monotonic() + settings.job_timeout_s
            while job.status not in queue.TERMINAL:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"{kind} job {job.id} did not finish in time")
                time.sleep(1.0)
                s.expire_all()
                job = s.get(Job, job.id)
                assert job is not None
            if job.status != "succeeded":
                raise RuntimeError(job.error or f"{kind} job {job.status}")
            return dict(job.result or {}).get("result", job.result or {})

    return run_job


def _tool_context(principal: Principal, settings: Settings) -> Any:
    from strata.agent import ToolContext

    owner = principal.user_id
    return ToolContext(
        user_id=str(owner),
        run_job=_make_run_job(owner, settings),
        list_datasets=lambda _uid: _list_datasets(owner),
        get_dataset_coordinates=lambda did, space: _dataset_coordinates(owner, did, space),
    )


# ------------------------------------------------------------------ streaming


@router.post(
    "/sessions/{session_id}/messages",
    summary="Send a message (SSE stream)",
    dependencies=[Depends(rate_limit_expensive)],
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-Sent Events"}},
)
async def post_message(
    session_id: uuid.UUID,
    body: ChatMessageCreate,
    request: Request,
    db: DbDep,
    principal: PrincipalDep,
    settings: SettingsDep,
) -> EventSourceResponse:
    chat = _owned(db, principal, session_id)
    if not settings.llm_configured:
        raise ApiError(
            503,
            f"research assistant unavailable: no API key configured for {settings.llm_provider}",
            "llm_unavailable",
        )
    try:
        import strata.agent as agent_mod
    except ImportError as exc:
        raise ApiError(503, f"agent module unavailable: {exc}", "llm_unavailable") from exc

    prior = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat.id)
            .order_by(ChatMessage.seq.desc())
            .limit(HISTORY_TURNS)
        )
    )[::-1]
    history = [{"role": m.role, "content": m.content} for m in prior if m.content]
    next_seq = (
        db.scalar(select(func.max(ChatMessage.seq)).where(ChatMessage.session_id == chat.id)) or 0
    ) + 1
    db.add(
        ChatMessage(
            session_id=chat.id,
            owner_id=principal.user_id,
            seq=next_seq,
            role="user",
            content=body.content,
        )
    )
    if not chat.title:
        chat.title = body.content[:80]
    chat.updated_at = utcnow()
    db.commit()

    ctx = _tool_context(principal, settings)
    cancel = asyncio.Event()

    async def events() -> AsyncIterator[dict[str, Any]]:
        tool_calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        text: list[str] = []
        usage: dict[str, Any] | None = None
        error: str | None = None
        done: dict[str, Any] | None = None
        try:
            async for ev in agent_mod.stream_chat(history, body.content, ctx=ctx, cancel=cancel):
                if await request.is_disconnected():
                    cancel.set()
                t = ev.get("type")
                if t == "text_delta":
                    text.append(ev.get("text", ""))
                elif t == "tool_call":
                    tool_calls.append(ev)
                elif t == "tool_result":
                    tool_results.append(ev)
                elif t == "error":
                    error = ev.get("message")
                elif t == "done":
                    done = ev
                    usage = ev.get("usage")
                    continue  # sent after persisting
                yield {"event": t, "data": json.dumps(ev, default=str)}
        except asyncio.CancelledError:
            cancel.set()
            error = "client disconnected"
            raise
        finally:
            msg_id = _persist(
                chat.id,
                principal.user_id,
                next_seq + 1,
                text,
                done,
                tool_calls,
                tool_results,
                usage,
                error,
            )
        yield {"event": "saved", "data": json.dumps({"type": "saved", "message_id": str(msg_id)})}
        if done is not None:
            payload = {k: v for k, v in done.items() if k != "transcript"}
            yield {"event": "done", "data": json.dumps(payload, default=str)}

    return EventSourceResponse(
        events(), ping=15, headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


def _persist(
    session_id: uuid.UUID,
    owner: uuid.UUID,
    seq: int,
    text: list[str],
    done: dict[str, Any] | None,
    tool_calls: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    usage: dict[str, Any] | None,
    error: str | None,
) -> uuid.UUID:
    content = (done or {}).get("answer") or "".join(text)
    mid = uuid.uuid4()
    with get_sessionmaker()() as s, s.begin():
        s.add(
            ChatMessage(
                id=mid,
                session_id=session_id,
                owner_id=owner,
                seq=seq,
                role="assistant",
                content=content,
                tool_calls=tool_calls,
                tool_results=tool_results,
                grounding=(done or {}).get("grounding"),
                citations=(done or {}).get("citations", []),
                usage={
                    **(usage or {}),
                    "steps": (done or {}).get("steps"),
                    "transcript": (done or {}).get("transcript", []),
                },
                error=error,
            )
        )
        cs = s.get(ChatSession, session_id)
        if cs is not None:
            cs.updated_at = utcnow()
    return mid


__all__ = ["router", "ChatMessageOut"]
