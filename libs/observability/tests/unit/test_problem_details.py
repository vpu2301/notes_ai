"""RFC 9457 rendering of ``HTTPException`` bodies.

A raiser may hand ``HTTPException`` a plain string or a whole problem
document as ``detail``. Both must come out as one flat problem+json body:
a client branches on ``type`` and shows ``detail`` to a person, and a
Python repr of a dict is neither.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from observability.problem_details import PROBLEM_CONTENT_TYPE, register_exception_handlers


def _app() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/plain")
    async def _plain() -> None:
        raise HTTPException(404, detail="note not found")

    @app.get("/document")
    async def _document() -> None:
        raise HTTPException(
            422,
            detail={
                "type": "https://errors.notes-ai/missing-read-purpose",
                "title": "Read purpose required",
                "detail": "Non-author reads must include ?purpose=<value>",
                "allowed": ["review", "audit"],
            },
        )

    @app.get("/extras")
    async def _extras() -> None:
        exc = HTTPException(401, detail="code needed")
        exc.problem_extras = {"code": "otp_required"}  # type: ignore[attr-defined]
        raise exc

    return TestClient(app, raise_server_exceptions=False)


def test_string_detail_is_unchanged() -> None:
    resp = _app().get("/plain")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    body = resp.json()
    assert body["title"] == "Not Found"
    assert body["detail"] == "note not found"
    assert body["status"] == 404
    assert body["instance"].startswith("urn:uuid:")


def test_dict_detail_is_lifted_to_a_flat_problem() -> None:
    body = _app().get("/document").json()
    assert body["type"] == "https://errors.notes-ai/missing-read-purpose"
    assert body["title"] == "Read purpose required"
    assert body["detail"] == "Non-author reads must include ?purpose=<value>"
    assert body["allowed"] == ["review", "audit"]
    assert body["status"] == 422
    # Nothing nested, nothing repr'd.
    assert "{'type'" not in resp_text(body)


def test_problem_extras_still_attach() -> None:
    body = _app().get("/extras").json()
    assert body["code"] == "otp_required"
    assert body["detail"] == "code needed"


def resp_text(body: dict) -> str:
    return " ".join(str(v) for v in body.values())


def test_problem_extras_may_name_the_type() -> None:
    """asr-service's job endpoints attach ``{"type_uri": …}`` through
    ``problem_extras``. That key used to collide with the handler's own
    ``type_uri=`` keyword, so every such 409/410 died inside the handler
    and reached the client as a 500 "An unexpected error occurred."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/not-ready")
    async def _not_ready() -> None:
        exc = HTTPException(409, detail="job is in status 'running', not 'complete'")
        exc.problem_extras = {  # type: ignore[attr-defined]
            "type_uri": "urn:mdx:asr:result:not-ready",
            "job_status": "running",
        }
        raise exc

    resp = TestClient(app).get("/not-ready")
    assert resp.status_code == 409
    body = resp.json()
    assert body["type"] == "urn:mdx:asr:result:not-ready"
    assert body["job_status"] == "running"
    assert "type_uri" not in body
    assert body["detail"] == "job is in status 'running', not 'complete'"
