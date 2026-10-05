"""Response headers and request-size limits.

HSTS belongs at the TLS terminator, not here. `/auth/*` gets `Cache-Control:
no-store` (RFC 6749 §5.1 for tokens; the rest carries equally sensitive data).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 16 KiB: the largest legitimate body is hundreds of bytes.
MAX_BODY_BYTES = 16 * 1024

# The revert/lockdown pages need inline styles and nothing else.
HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers.setdefault("Content-Security-Policy", HTML_CSP)
            # A revert page acts on load; never framable.
            response.headers.setdefault("X-Frame-Options", "DENY")

        if request.url.path.startswith("/auth") or request.url.path.startswith("/admin"):
            # `setdefault`: the OAuth route sets its own `no-store` and JWKS wants `public, max-age=300`.
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("Pragma", "no-cache")

        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    """Refuse oversized bodies with 413 by `Content-Length` only; chunked requests pass (the ASGI server bounds them)."""

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
