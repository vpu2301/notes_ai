"""``POST /v1/notes/{id}/ask`` — "Ask this note".

The chat bar at the bottom of a note (Mac app, web) sends one question plus
the conversation so far; the answer comes from the chat provider the model
registry routes this environment to (ADR-0046), grounded in the note's
current content and — when the note came from a recording — its
transcript, fetched from asr-service with the caller's own bearer.

Nothing is stored: the conversation lives in the client. The audit event
carries counts and the backend that answered, never the question or the
answer (content, ADR-0031).
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from audit import Severity
from auth import Claims
from db import tenant_connection
from models import ConfigError, ProviderError

from .. import audit_kinds
from ..config import settings
from ..deps import get_state, requires
from ..domain import access
from ..domain import notes_repository as repo
from ..domain.ask import NoteAsker, Turn, sections_for_prompt
from .notes_from_transcript import _fetch_transcript, _transcript_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

MAX_HISTORY = 12


class AskTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8_000)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)
    # The conversation so far, oldest first; the client keeps it.
    history: list[AskTurn] = Field(default_factory=list, max_length=MAX_HISTORY)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("question is blank")
        return value


class AskResponse(BaseModel):
    answer: str
    backend: str
    model_id: str


_asker: NoteAsker | None = None


def get_asker() -> NoteAsker:
    global _asker
    if _asker is None:
        _asker = NoteAsker(
            config_path=settings.models_config,
            env=settings.registry_env(),
            environ=settings.registry_environ(),
            max_tokens=settings.ask_max_tokens,
            max_chars=settings.ask_context_chars,
        )
    return _asker


def _unavailable(detail: str, *, code: str, **extras: str) -> HTTPException:
    """503 as an RFC 9457 problem: human `detail`, machine `code` (+ `kind`)."""
    exc = HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)
    exc.problem_extras = {"code": code, **extras}  # type: ignore[attr-defined]
    return exc


@router.post(
    "/{note_id}/ask",
    response_model=AskResponse,
    summary="Ask a question about this note (answered by the model over note + transcript).",
    responses={
        503: {
            "description": "Problem with `code` `model_not_configured` (no chat backend for "
            "this environment) or `model_unavailable` (the backend failed; `kind` names "
            "the failure class)."
        }
    },
)
async def ask_note(
    note_id: UUID,
    body: AskRequest,
    request: Request,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> AskResponse:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        version = await repo.fetch_version(conn, version_id=row.current_version_id)
        source_job_id = await conn.fetchval(
            "SELECT source_asr_job_id FROM notes WHERE id = $1", note_id
        )
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="note not found")

    # The transcript is context, not a requirement: a note whose recording
    # is gone (or whose asr-service is down) is still answerable from its text.
    transcript = ""
    if source_job_id is not None:
        try:
            result = await _fetch_transcript(
                source_job_id, auth_header=request.headers.get("authorization") or ""
            )
            transcript = _transcript_text(result)
        except HTTPException as exc:
            logger.info("ask.transcript_unavailable", extra={"status": exc.status_code})

    history = [Turn(role=t.role, text=t.text) for t in body.history]
    try:
        answer = await get_asker().answer(
            workspace_id=str(claims.tid),
            title=version.content.title or row.title,
            code=row.code,
            sections=sections_for_prompt(version.content),
            transcript=transcript,
            history=history,
            question=body.question,
        )
    except ConfigError as exc:
        logger.warning("ask.model_not_configured: %s", exc)
        raise _unavailable(
            "No model is set up to answer questions in this environment.",
            code="model_not_configured",
        ) from exc
    except ProviderError as exc:
        logger.warning("ask.model_unavailable: %s", exc.kind)
        raise _unavailable(
            "The model could not answer right now. Try again in a moment.",
            code="model_unavailable",
            kind=str(exc.kind),
        ) from exc

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_ASKED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=str(note_id),
        payload={
            "backend": answer.backend,
            "model_id": answer.model_id,
            "question_chars": len(body.question),
            "answer_chars": len(answer.text),
            "with_transcript": bool(transcript),
            "latency_ms": answer.latency_ms,
        },
        severity=Severity.INFO,
    )
    return AskResponse(answer=answer.text, backend=answer.backend, model_id=answer.model_id)
