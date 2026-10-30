"""Security headers for every API response."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

API_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
# HTML reports and the OpenAPI docs page need inline styles/scripts from the docs CDN.
REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'"
DOCS_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: "
    "https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for k, v in API_HEADERS.items():
            response.headers.setdefault(k, v)
        path = request.url.path
        if path.endswith("/docs") or path.endswith("/redoc"):
            response.headers.setdefault("Content-Security-Policy", DOCS_CSP)
        else:
            response.headers.setdefault("Content-Security-Policy", API_CSP)
        # User data must never be cached by shared caches.
        if path.startswith("/api/v1/") and not path.startswith("/api/v1/reference"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
