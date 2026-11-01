"""Uniform JSON error responses: {"detail": str, "code": str, ...}."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("strata.api")


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str = "error",
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail)
        self.status_code, self.detail, self.code = status_code, detail, code
        self.headers, self.extra = headers, extra


def not_found(what: str = "resource") -> ApiError:
    # Same response for "missing" and "owned by someone else": no existence oracle.
    return ApiError(404, f"{what} not found", "not_found")


_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.detail, "code": exc.code, **exc.extra},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.detail, "code": _CODES.get(exc.status_code, "error")},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Do not echo submitted values back (they may contain genetic data).
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            {"detail": "request validation failed", "code": "validation_error", "errors": errors},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return JSONResponse(
            {"detail": "internal server error", "code": "internal"}, status_code=500
        )
