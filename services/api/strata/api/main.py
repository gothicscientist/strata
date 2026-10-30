"""FastAPI application: `uvicorn strata.api.main:app`."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.formparsers import MultiPartParser
from starlette.types import ASGIApp, Receive, Scope, Send

from strata import __version__
from strata.api.deps import rate_limit_default
from strata.api.errors import install_error_handlers
from strata.api.routers import analyses, auth, chat, datasets, examples, health, jobs, reference
from strata.config import Settings, get_settings
from strata.security.headers import SecurityHeadersMiddleware
from strata.security.logging import install_log_redaction

PREFIX = "/api/v1"

TAGS = [
    {"name": "health", "description": "Liveness and honest capability flags."},
    {"name": "auth", "description": "Guest workspaces (signed tokens) and Supabase sessions."},
    {"name": "reference", "description": "Public reference library: AADR-derived populations, "
                                         "publications and coordinate spaces."},
    {"name": "datasets", "description": "User uploads (G25 coordinates, raw DNA, VCF), parsed in "
                                        "memory, stored encrypted; delete crypto-shreds."},
    {"name": "analyses", "description": "Exploratory PCA/G25 fits and formal qpAdm tests, run as "
                                        "jobs, with reproducible reports."},
    {"name": "comparisons", "description": "Saved side-by-side model comparisons."},
    {"name": "jobs", "description": "Job status for queued analyses."},
    {"name": "examples", "description": "Precomputed real example analyses."},
    {"name": "chat", "description": "LLM research assistant (SSE). Never receives genotypes."},
]


class BodySizeLimit:
    """Rejects request bodies above the configured limit before they are buffered."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        cl = headers.get(b"content-length")
        if cl is not None and cl.isdigit() and int(cl) > self.max_bytes:
            await _reject(send)
            return
        seen = 0

        async def limited() -> Any:
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_bytes:
                    raise _TooLargeError()
            return msg

        try:
            await self.app(scope, limited, send)
        except _TooLargeError:
            await _reject(send)


class _TooLargeError(Exception):
    pass


async def _reject(send: Send) -> None:
    body = b'{"detail":"request body too large","code":"payload_too_large"}'
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    install_log_redaction(settings.log_level)
    # Keep uploaded files in memory (never spooled to a temp file on disk).
    MultiPartParser.spool_max_size = settings.max_upload_bytes + 1

    @asynccontextmanager
    async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
        if settings.database_url.startswith("sqlite"):
            from strata.db.session import init_db

            init_db()
        yield

    app = FastAPI(
        title="Strata API",
        version=__version__,
        description=(
            "Computational population genetics: exploratory PCA / G25 admixture modelling, "
            "formal qpAdm testing, a reference library of ancient genomes, and an LLM "
            "research assistant. Exploratory results are always labelled as such and are "
            "distinct from formal f-statistics tests."
        ),
        openapi_tags=TAGS,
        docs_url=f"{PREFIX}/docs",
        redoc_url=f"{PREFIX}/redoc",
        openapi_url=f"{PREFIX}/openapi.json",
        lifespan=lifespan,
        license_info={"name": "AGPL-3.0-or-later"},
    )
    install_error_handlers(app)
    api = APIRouter(prefix=PREFIX, dependencies=[Depends(rate_limit_default)])
    for r in (health.router, auth.router, reference.router, datasets.router, analyses.router,
              jobs.router, examples.router, chat.router):
        api.include_router(r)
    app.include_router(api)

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
        expose_headers=["Retry-After", "Content-Disposition"],
        max_age=600,
    )
    # Body limit: upload limit plus multipart overhead.
    app.add_middleware(BodySizeLimit, max_bytes=settings.max_upload_bytes + 1024 * 1024)
    return app


app = create_app()
