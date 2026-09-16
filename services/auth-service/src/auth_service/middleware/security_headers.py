"""Response headers and request-size limits for auth-service (IDX-B3 E).

Two middlewares, both deliberately small.

**What is here and what is not.** HSTS is set at the TLS terminator, not
in FastAPI: an application-set `Strict-Transport-Security` on a response
that arrived over plain HTTP is ignored by browsers and misleading to
whoever reads the code. `Secure` on the refresh cookie is likewise a
terminator-dependent setting and lives in config
(`AUTH_COOKIE_SECURE`). What FastAPI can set truthfully is set here.

**Why `Cache-Control: no-store` on `/auth/*`.** These responses carry
access tokens, one-time codes' challenge ids, session lists and email
addresses. A shared proxy or a browser back-button that re-serves one of
them is the whole risk; RFC 6749 §5.1 requires it for token responses,
and the same reasoning covers the rest of the surface.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 16 KiB. The largest legitimate body on this service is an OAuth form or
# a JSON login — hundreds of bytes. The limit exists so an unauthenticated
# endpoint cannot be made to buffer megabytes per connection.
MAX_BODY_BYTES = 16 * 1024

# A page rendered by this service (the email-revert and lockdown pages)
# needs its own inline styles and nothing else at all: no scripts, no
# images, no frames, no form posts. `default-src 'none'` with one
# exception is the tightest policy that still renders.
HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)

        # Applied to everything: neither costs anything and both close a
        # class of browser-side mistake rather than a specific bug.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers.setdefault("Content-Security-Policy", HTML_CSP)
            # A revert page acts on load; framing it is the setup for a
            # click that the user did not mean to make.
            response.headers.setdefault("X-Frame-Options", "DENY")

        if request.url.path.startswith("/auth") or request.url.path.startswith("/admin"):
            # `setdefault` so the OAuth route's own explicit `no-store`
            # (RFC 6749 §5.1) is not overwritten, and so the JWKS
            # document keeps the `public, max-age=300` it wants — that one
            # is a public key, and caching it is the point.
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("Pragma", "no-cache")

        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    """Refuse oversized request bodies with 413 before they are parsed.

    Checks `Content-Length` only. A chunked request without one is passed
    through: Starlette streams it, and rejecting all unlengthed requests
    would break legitimate clients for a limit that ASGI servers already
    enforce at a coarser level. The value here is stopping the easy case
    cheaply, not being a substitute for the server's own limits.
    """

    def __init__(
        self, app: Callable[..., Awaitable[object]], *, max_bytes: int = MAX_BODY_BYTES
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._max = max_bytes

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        raw = request.headers.get("content-length")
        if raw:
            try:
                length = int(raw)
            except ValueError:
                length = 0
            if length > self._max:
                logger.info(
                    "auth.body_too_large",
                    extra={"path": request.url.path, "content_length": length},
                )
                return JSONResponse(
                    status_code=413,
                    media_type="application/problem+json",
                    content={
                        "type": "about:blank",
                        "title": "Payload Too Large",
                        "status": 413,
                        "detail": f"request bodies are limited to {self._max} bytes",
                        "code": "body_too_large",
                    },
                )
        return await call_next(request)
