"""Sprint-14 conversation finalize → note draft (pure, fakes only).

Two contracts:

* ``dialogue_text`` renders reviewable speaker turns — client-supplied
  names or the neutral SPEAKER_N defaults, consecutive same-speaker
  turns merged, and an unresolved speaker gets the honesty label
  instead of being folded into a participant.
* ``create_conversation_draft`` posts through the EXISTING
  ``POST /v1/notes`` surface with the caller's bearer, links back
  via ``source_session_id`` + ``transcript_segment_ids``, and NEVER
  raises: every failure degrades to a ``conversation.draft.create_failed``
  audit row (the transcript is already persisted when this runs).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from dictation_service import audit_kinds
from dictation_service.integrations.note_client import DraftResult
from dictation_service.session.draft import create_conversation_draft, dialogue_text
from dictation_service.session.finalize import FinalizeResult
from dictation_service.session.manager import SessionContext

SEG_ID_1 = str(uuid4())
SEG_ID_2 = str(uuid4())


# ── Fakes ────────────────────────────────────────────────────────────


class _FakeAuditWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)

    def kinds(self) -> list[str]:
        return [e["kind"] for e in self.events]

    def only(self) -> dict[str, Any]:
        assert len(self.events) == 1, f"expected one audit event, got {self.kinds()}"
        return self.events[0]


class _FakeNoteClient:
    def __init__(self, result: DraftResult | None) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def create_draft(self, *, bearer: str, body: dict[str, Any]) -> DraftResult | None:
        self.calls.append({"bearer": bearer, "body": body})
        return self._result


@dataclass
class _FakeTemplateDoc:
    sections: list[dict[str, Any]]
    schema_version: int = 3


def _transcript() -> list[dict[str, Any]]:
    return [
        {"id": SEG_ID_1, "text": "Що в нас на порядку денному?", "speaker_name": "Alice"},
        {"id": SEG_ID_2, "text": "Огляд релізу.", "speaker_name": "Bob"},
    ]


def _state(*, draft: DraftResult | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        note_client=_FakeNoteClient(draft),
        audit_writer=_FakeAuditWriter(),
    )


def _ctx(
    *,
    bearer: str | None = "tok",
    template_id: Any = "set",
    template_doc: Any = "set",
    language: str = "uk",
) -> SessionContext:
    ctx = SessionContext(
        session_id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        language=language,
        vocabulary_hint="",
        target_kind="generic",
        template_id=uuid4() if template_id == "set" else template_id,
        mode="conversation",
        bearer=bearer,
    )
    ctx.template_doc = (
        _FakeTemplateDoc(sections=[{"id": "summary", "asr_prompt": ""}])
        if template_doc == "set"
        else template_doc
    )
    return ctx


def _result(transcript: list[dict[str, Any]] | None) -> FinalizeResult:
    return FinalizeResult(
        audio_file_id=None,
        truncated=False,
        transcript_segments=len(transcript or []),
        duration_ms=12_000,
        transcript=transcript,
    )


# ── dialogue_text ────────────────────────────────────────────────────


def test_dialogue_uses_client_supplied_names() -> None:
    text = dialogue_text(_transcript(), "uk")
    assert text == "Alice: Що в нас на порядку денному?\nBob: Огляд релізу."


def test_unnamed_speakers_render_neutral_defaults() -> None:
    text = dialogue_text(
        [
            {"text": "First point.", "speaker_name": None, "speaker": "S1"},
            {"text": "Second point.", "speaker_name": None, "speaker": "S2"},
        ],
        "en",
    )
    assert text == "SPEAKER_1: First point.\nSPEAKER_2: Second point."


def test_consecutive_same_speaker_segments_merge_onto_one_line() -> None:
    text = dialogue_text(
        [
            {"text": "Добрий день.", "speaker_name": "Alice"},
            {"text": "Почнімо.", "speaker_name": "Alice"},
            {"text": "Дякую.", "speaker_name": "Bob"},
        ],
        "uk",
    )
    assert text == "Alice: Добрий день. Почнімо.\nBob: Дякую."


def test_unresolved_speaker_renders_the_honesty_label() -> None:
    text = dialogue_text(
        [
            {"text": "Добрий день.", "speaker_name": "Alice"},
            {"text": "Щось нерозбірливе.", "speaker_name": None, "speaker": "UNKNOWN"},
        ],
        "uk",
    )
    assert text == "Alice: Добрий день.\nUNKNOWN: Щось нерозбірливе."


def test_empty_segments_are_skipped() -> None:
    text = dialogue_text(
        [
            {"text": "   ", "speaker_name": "Alice"},
            {"text": "Готово.", "speaker_name": "Bob"},
        ],
        "uk",
    )
    assert text == "Bob: Готово."


# ── create_conversation_draft — happy path ───────────────────────────


async def test_draft_posts_the_note_body() -> None:
    state = _state(draft=DraftResult(note_id="n1", code="C-1", version_id="v1"))
    ctx = _ctx()

    await create_conversation_draft(ctx, state, finalize_result=_result(_transcript()))

    assert len(state.note_client.calls) == 1
    call = state.note_client.calls[0]
    assert call["bearer"] == "tok"

    body = call["body"]
    assert body["source_session_id"] == str(ctx.session_id)
    assert body["co_author_ids"] == []
    assert "patient_id" not in body

    content = body["content"]
    assert content["template_id"] == str(ctx.template_id)
    assert content["template_schema_version"] == 3
    assert content["title"] == "Зустріч (розмовний режим)"

    section = content["sections"][0]
    assert section["section_key"] == "summary"
    assert section["transcript_segment_ids"] == [SEG_ID_1, SEG_ID_2]
    assert section["text"] == "Alice: Що в нас на порядку денному?\nBob: Огляд релізу."

    event = state.audit_writer.only()
    assert event["kind"] == audit_kinds.DRAFT_CREATED == "conversation.draft.created"
    assert event["target_kind"] == "note"
    assert event["target_id"] == "n1"
    assert event["payload"]["code"] == "C-1"
    assert event["payload"]["version_id"] == "v1"
    assert event["payload"]["segments"] == 2
    assert event["payload"]["session_id"] == str(ctx.session_id)


async def test_english_draft_gets_the_english_title() -> None:
    state = _state(draft=DraftResult(note_id="n2", code="C-2", version_id="v2"))
    ctx = _ctx(language="en")

    await create_conversation_draft(ctx, state, finalize_result=_result(_transcript()))

    body = state.note_client.calls[0]["body"]
    assert body["content"]["title"] == "Meeting (conversation)"


async def test_german_draft_gets_the_german_title() -> None:
    state = _state(draft=DraftResult(note_id="n3", code="C-3", version_id="v3"))
    ctx = _ctx(language="de")

    await create_conversation_draft(ctx, state, finalize_result=_result(_transcript()))

    body = state.note_client.calls[0]["body"]
    assert body["content"]["title"] == "Besprechung (Gesprächsmodus)"


# ── failure paths — audited, never raised ────────────────────────────


@pytest.mark.parametrize(
    ("ctx_kwargs", "transcript", "reason"),
    [
        ({}, None, "empty_transcript"),
        ({}, [], "empty_transcript"),
        ({"bearer": None}, "full", "no_bearer"),
        ({"template_id": None}, "full", "no_template"),
        ({"template_doc": None}, "full", "no_template"),
    ],
)
async def test_failures_audit_and_never_raise(
    ctx_kwargs: dict[str, Any],
    transcript: Any,
    reason: str,
) -> None:
    state = _state(draft=DraftResult(note_id="n1", code="C-1", version_id="v1"))
    ctx = _ctx(**ctx_kwargs)
    segments = _transcript() if transcript == "full" else transcript

    await create_conversation_draft(ctx, state, finalize_result=_result(segments))

    event = state.audit_writer.only()
    assert event["kind"] == audit_kinds.DRAFT_CREATE_FAILED
    assert event["payload"]["reason"] == reason
    assert event["severity"].value == "warn"
    assert event["target_id"] == str(ctx.session_id)
    assert state.note_client.calls == []  # never posted


async def test_template_without_a_section_key_is_audited() -> None:
    state = _state(draft=DraftResult(note_id="n1", code="C-1", version_id="v1"))
    ctx = _ctx()
    ctx.template_doc = _FakeTemplateDoc(sections=[{"name": "Підсумок"}])

    await create_conversation_draft(ctx, state, finalize_result=_result(_transcript()))

    assert state.audit_writer.only()["payload"]["reason"] == "template_has_no_section_key"
    assert state.note_client.calls == []


async def test_note_service_error_is_audited_after_the_post() -> None:
    state = _state(draft=None)
    ctx = _ctx()

    await create_conversation_draft(ctx, state, finalize_result=_result(_transcript()))

    assert len(state.note_client.calls) == 1  # it DID try
    event = state.audit_writer.only()
    assert event["kind"] == audit_kinds.DRAFT_CREATE_FAILED
    assert event["payload"]["reason"] == "note_service_error"
    assert audit_kinds.DRAFT_CREATED not in state.audit_writer.kinds()
