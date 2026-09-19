"""Request-ID stamping."""

import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class AnonymousCorsMiddleware(BaseHTTPMiddleware):
    """`/v1/shared/*` answers any origin, without credentials (Sprint 23).

    The recipient page may be embedded or fetched from wherever the link
    was opened; there is no cookie or bearer on that surface, so a
    wildcard origin gives away nothing. Mounted OUTSIDE the credentialed
    CORS middleware so a preflight from an unknown origin is answered
    here instead of refused there. Everything else keeps the allow-list.
    """

    PREFIX = "/v1/shared/"
    _HEADERS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, PUT, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "600",
    }

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if not request.url.path.startswith(self.PREFIX):
            return await call_next(request)
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=self._HEADERS)
        response = await call_next(request)
        for key, value in self._HEADERS.items():
            response.headers[key] = value
        if "access-control-allow-credentials" in response.headers:
            del response.headers["access-control-allow-credentials"]
        return response
