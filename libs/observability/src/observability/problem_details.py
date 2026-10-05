"""RFC 9457 Problem Details handlers; ``instance`` is a fresh ``urn:uuid:`` that is also logged for correlation."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"

_DEFAULT_TYPE = "about:blank"

_HTTP_STATUS_TITLES: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    415: "Unsupported Media Type",
    422: "Unprocessable Content",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


class ProblemDetails(BaseModel):
    """RFC 9457 Problem Details document."""

    type: str = Field(default=_DEFAULT_TYPE)
    title: str
    status: int
    detail: str | None = None
    instance: str
    # Extension members are allowed; FastAPI emits `model_extra` if set.

    model_config = {"extra": "allow"}


def _new_instance() -> str:
    return f"urn:uuid:{uuid4()}"


def _problem(
    *, status: int, detail: str | None, type_uri: str | None = None, **extras: Any
) -> ProblemDetails:
    return ProblemDetails(
        type=type_uri or _DEFAULT_TYPE,
        title=_HTTP_STATUS_TITLES.get(status, "Error"),
        status=status,
        detail=detail,
        instance=_new_instance(),
        **extras,
    )


def _json_response(p: ProblemDetails, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=p.status,
        content=p.model_dump(mode="json", exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
        headers=headers,
    )


async def http_exception_handler(
    request: Request, exc: HTTPException | StarletteHTTPException
) -> JSONResponse:
    # A raiser may set `exc.problem_extras` (a dict) to add RFC 9457 extension members.
    extras = dict(getattr(exc, "problem_extras", None) or {})
    # Popped so it cannot collide with the ``type_uri=`` keyword below (that collision 500'd every such 409/410).
    extra_type = extras.pop("type_uri", None)
    detail = exc.detail
    type_uri: str | None = extra_type if isinstance(extra_type, str) else None
    title: str | None = None
    if isinstance(detail, dict):
        # An inline problem document: lift the RFC 9457 members, keep the rest as extensions.
        body = dict(detail)
        if isinstance(body.get("type"), str):
            type_uri = body.pop("type")
        else:
            body.pop("type", None)
        title = body.pop("title", None) if isinstance(body.get("title"), str) else None
        raw_detail = body.pop("detail", None)
        detail = raw_detail if isinstance(raw_detail, str) else None
        body.pop("status", None)
        body.pop("instance", None)
        extras = {**body, **extras}
    elif detail is not None and not isinstance(detail, str):
        detail = str(detail)
    p = _problem(status=exc.status_code, detail=detail, type_uri=type_uri, **extras)
    if title:
        p.title = title
    logger.info(
        "http_exception",
        extra={
            "status": exc.status_code,
            "instance": p.instance,
            "path": str(request.url.path),
            "method": request.method,
        },
    )
    # Keeps WWW-Authenticate on 401.
    extra_headers = getattr(exc, "headers", None)
    return _json_response(p, headers=extra_headers)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Pydantic v2 puts a raw exception into ctx["error"], which is not JSON-serializable.
    errors = []
    for e in exc.errors():
        if isinstance(e.get("ctx"), dict):
            e = {**e, "ctx": {k: str(v) for k, v in e["ctx"].items()}}
        errors.append(e)
    p = _problem(
        status=422,
        detail="Request validation failed.",
        type_uri="https://datatracker.ietf.org/doc/html/rfc9457#section-3",
        errors=errors,
    )
    logger.info(
        "validation_error",
        extra={
            "instance": p.instance,
            "path": str(request.url.path),
            "method": request.method,
        },
    )
    return _json_response(p)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    p = _problem(status=500, detail="An unexpected error occurred.")
    logger.exception(
        "unhandled_exception",
        extra={"instance": p.instance, "path": str(request.url.path), "method": request.method},
    )
    return _json_response(p)


def register_exception_handlers(app: FastAPI) -> None:
    """Install RFC 9457 handlers for HTTPException, validation errors, and unhandled."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
