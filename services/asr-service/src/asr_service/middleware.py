"""Service-local middleware. Cross-cutting error handling lives in libs/observability."""

import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# When the request's headers arrived (before its body): the start of an upload's span.
request_received_at: ContextVar[datetime | None] = ContextVar("request_received_at", default=None)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a stable X-Request-ID header to every request and response."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_received_at.set(datetime.now(UTC))
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
