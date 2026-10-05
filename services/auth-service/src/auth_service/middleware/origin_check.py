"""Origin check for browser state changes: a mutating request must carry an allowed ``Origin``/``Referer``.

Native clients are exempt only with ``X-Client-Type: macos|ios`` AND no ``Origin``
(a browser cannot suppress its own Origin header).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import urlsplit

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..domain.transport import ClientType, client_type_of

logger = logging.getLogger(__name__)

STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ERROR_CODE = "origin_not_allowed"

# `/auth/oauth/token` uses no ambient credential (CSRF is impossible) and room
# devices send neither `Origin` nor `X-Client-Type`.
EXEMPT_PREFIXES: tuple[str, ...] = ("/auth/oauth/",)


def _origin_of(value: str) -> str | None:
    """``https://app.example.com/some/path`` → ``https://app.example.com``."""
    parts = urlsplit(value.strip())
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return _origin_of(origin)
    referer = request.headers.get("referer")
    if referer:
        return _origin_of(referer)
    return None


class OriginCheckMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Callable[..., Awaitable[object]],
        *,
        allowed_origins: Iterable[str],
        path_prefix: str = "/auth",
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._allowed = {o.rstrip("/").lower() for o in allowed_origins if o}
        self._prefix = path_prefix

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if request.method not in STATE_CHANGING or not path.startswith(self._prefix):
            return await call_next(request)
        if any(path.startswith(p) for p in EXEMPT_PREFIXES):
            return await call_next(request)

        origin = request_origin(request)
        client_type = client_type_of(request)
        if client_type is not ClientType.WEB and origin is None:
            return await call_next(request)  # a native app: no browser, no Origin
        if origin is not None and origin in self._allowed:
            return await call_next(request)

        logger.info(
            "auth.origin_rejected",
            extra={
                "path": request.url.path,
                "client_type": str(client_type),
                "has_origin": origin is not None,
            },
        )
        return JSONResponse(
            status_code=403,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Forbidden",
                "status": 403,
                "detail": "this request's origin is not allowed",
                "code": ERROR_CODE,
            },
        )
