"""Conversation finalize → note draft via POST /v1/notes (sprint 14).

The sprint-08 hand-off: drafts go through the EXISTING note-service
surface, authored as the caller (their bearer), linked back via
``source_session_id`` and ``transcript_segment_ids`` (the sprint-08
field, fed by the segment UUIDs minted in the conversation transcript).

Failure policy: the transcript is already persisted when this runs; a
missed draft degrades to a ``conversation.draft.create_failed`` audit
row — never a failed finalize.
"""

from __future__ import annotations

import logging
from typing import Any

from audit import Severity

from .. import audit_kinds
from ..diarization.mapping import default_name
from .finalize import FinalizeResult
from .manager import SessionContext

logger = logging.getLogger(__name__)

_DRAFT_TITLES = {
    "uk": "Зустріч (розмовний режим)",
    "en": "Meeting (conversation)",
    "de": "Besprechung (Gesprächsmodus)",
}


def dialogue_text(transcript: list[dict[str, Any]], language: str) -> str:
    """Render the diarized transcript as reviewable speaker-turn lines.

    Names are the finalize-time mapping (neutral ``SPEAKER_N`` defaults
    or the client-supplied naming); an unresolved speaker renders as the
    honesty label ``UNKNOWN``, never silently merged into a participant.
    ``language`` is accepted for symmetry with the draft titles; speaker
    names are client-supplied and not localised.
    """
    del language  # names are client-supplied, not localised
    lines: list[str] = []
    prev_key: object = object()
    for seg in transcript:
        name = seg.get("speaker_name")
        key = name if name is not None else seg.get("speaker")
        label = name or default_name(str(seg.get("speaker") or "UNKNOWN"))
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        if key == prev_key and lines:
            lines[-1] = f"{lines[-1]} {text}"
        else:
            lines.append(f"{label}: {text}")
        prev_key = key
    return "\n".join(lines)


async def create_conversation_draft(
    ctx: SessionContext,
    state: Any,
    *,
    finalize_result: FinalizeResult,
) -> None:
    transcript = finalize_result.transcript or []

    async def _fail(reason: str) -> None:
        logger.warning(
            "conversation.draft_skipped",
            extra={"session_id": str(ctx.session_id), "reason": reason},
        )
        await state.audit_writer.write_event(
            tenant_id=ctx.tenant_id,
            kind=audit_kinds.DRAFT_CREATE_FAILED,
            actor_sub=ctx.user_id,
            target_kind="dictation_session",
            target_id=str(ctx.session_id),
            payload={"reason": reason},
            severity=Severity.WARN,
        )

    if not transcript:
        await _fail("empty_transcript")
        return
    if ctx.bearer is None:
        await _fail("no_bearer")
        return
    if ctx.template_id is None or ctx.template_doc is None or not ctx.template_doc.sections:
        # POST /v1/notes requires an explicit template; a conversation
        # started without one keeps its transcript and the user creates
        # the note manually. Documented in dictation-ws-v2.md.
        await _fail("no_template")
        return

    first_section = ctx.template_doc.sections[0]
    section_key = str(first_section.get("id") or first_section.get("section_key") or "")
    if not section_key:
        await _fail("template_has_no_section_key")
        return

    segment_ids = [seg["id"] for seg in transcript if seg.get("id")]
    title = _DRAFT_TITLES.get(ctx.language, _DRAFT_TITLES["en"])
    body = {
        "content": {
            "template_id": str(ctx.template_id),
            "template_schema_version": ctx.template_doc.schema_version,
            "title": title,
            "sections": [
                {
                    "section_key": section_key,
                    "text": dialogue_text(transcript, ctx.language),
                    "transcript_segment_ids": segment_ids,
                    "field_specific_metadata": {},
                }
            ],
        },
        "co_author_ids": [],
        "source_session_id": str(ctx.session_id),
    }

    draft = await state.note_client.create_draft(bearer=ctx.bearer, body=body)
    if draft is None:
        await _fail("note_service_error")
        return

    await state.audit_writer.write_event(
        tenant_id=ctx.tenant_id,
        kind=audit_kinds.DRAFT_CREATED,
        actor_sub=ctx.user_id,
        target_kind="note",
        target_id=draft.note_id,
        payload={
            "session_id": str(ctx.session_id),
            "code": draft.code,
            "version_id": draft.version_id,
            "segments": len(segment_ids),
        },
        severity=Severity.INFO,
    )
    logger.info(
        "conversation.draft_created",
        extra={"session_id": str(ctx.session_id), "note_id": draft.note_id},
    )
