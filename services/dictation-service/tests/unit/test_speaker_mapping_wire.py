"""Speaker-naming wire contract (handler helpers, pure).

The naming state itself is proven in ``test_diarization_mapping.py``;
this pins how it reaches the wire:

* ``_current_mapping_hint`` — what rides along on every v2 partial/final
  (neutral SPEAKER_N defaults, then the client's names).
* the ``SetSpeakerMapping`` branch of ``_on_text`` — the manual naming
  is authoritative from the moment received: audited, acknowledged with
  ``manual=true, confidence=1.0``, and reflected in later hints.

No DB, no WebSocket, no models.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from dictation_service import audit_kinds
from dictation_service.diarization.mapping import SpeakerNaming
from dictation_service.session.manager import SessionContext
from dictation_service.ws.handler import (
    _current_mapping_hint,
    _on_text,
)


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    def frames(self) -> list[dict[str, Any]]:
        return [json.loads(t) for t in self.sent]


class _FakeAuditWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)

    def kinds(self) -> list[str]:
        return [e["kind"] for e in self.events]


def _ctx(
    *,
    mode: str = "conversation",
    naming: SpeakerNaming | None = None,
    manual: bool = False,
    ws: _FakeWebSocket | None = None,
) -> SessionContext:
    ctx = SessionContext(
        session_id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        language="uk",
        vocabulary_hint="",
        target_kind="generic",
        template_id=None,
        mode=mode,
        protocol_version=2,
        speaker_naming=naming,
        mapping_manual=manual,
    )
    ctx.ws = ws
    return ctx


def _state() -> SimpleNamespace:
    return SimpleNamespace(audit_writer=_FakeAuditWriter())


# ── _current_mapping_hint ────────────────────────────────────────────


def test_hint_is_none_without_naming_state() -> None:
    assert _current_mapping_hint(_ctx(naming=None)) is None


def test_hint_defaults_to_neutral_speaker_names() -> None:
    ctx = _ctx(naming=SpeakerNaming())
    assert _current_mapping_hint(ctx) == {"S1": "SPEAKER_1", "S2": "SPEAKER_2"}


def test_hint_is_a_copy_of_the_current_mapping() -> None:
    naming = SpeakerNaming()
    ctx = _ctx(naming=naming)

    hint = _current_mapping_hint(ctx)

    assert hint is not None
    hint["S1"] = "corrupted"  # mutating the hint must not corrupt state
    assert naming.name_for("S1") == "SPEAKER_1"


# ── SetSpeakerMapping over _on_text ──────────────────────────────────


def _set_mapping_frame(mapping: dict[str, str]) -> str:
    return json.dumps({"type": "set_speaker_mapping", "mapping": mapping})


async def test_manual_set_is_applied_audited_and_acknowledged() -> None:
    ws = _FakeWebSocket()
    naming = SpeakerNaming()
    ctx = _ctx(naming=naming, ws=ws)
    state = _state()

    cont = await _on_text(ctx, ws, state, _set_mapping_frame({"S1": "Alice", "S2": "Bob"}), None)

    assert cont is True  # the session stays open
    assert naming.manual is True
    assert naming.current.mapping == {"S1": "Alice", "S2": "Bob"}
    assert ctx.mapping_manual is True
    assert ctx.speaker_mapping_manual_sets == 1

    assert state.audit_writer.kinds() == [audit_kinds.SPEAKER_MAPPING_MANUAL_SET]
    event = state.audit_writer.events[0]
    assert event["kind"] == "conversation.speaker_mapping.manual_set"
    assert event["payload"]["mapping"] == {"S1": "Alice", "S2": "Bob"}
    assert event["target_id"] == str(ctx.session_id)

    frames = ws.frames()
    assert len(frames) == 1
    assert frames[0]["type"] == "speaker_mapping_updated"
    assert frames[0]["mapping"] == {"S1": "Alice", "S2": "Bob"}
    assert frames[0]["manual"] is True
    assert frames[0]["confidence"] == 1.0

    # The manual mapping is what rides on subsequent v2 frames.
    assert _current_mapping_hint(ctx) == {"S1": "Alice", "S2": "Bob"}


async def test_partial_naming_keeps_neutral_defaults_in_the_ack() -> None:
    ws = _FakeWebSocket()
    ctx = _ctx(naming=SpeakerNaming(), ws=ws)

    await _on_text(ctx, ws, _state(), _set_mapping_frame({"S1": "Alice"}), None)

    frames = ws.frames()
    assert frames[0]["mapping"] == {"S1": "Alice", "S2": "SPEAKER_2"}
    assert _current_mapping_hint(ctx) == {"S1": "Alice", "S2": "SPEAKER_2"}


async def test_set_speaker_mapping_on_a_dictation_session_is_rejected() -> None:
    ws = _FakeWebSocket()
    # A v2 dictation session: the message can arrive on the wire, but the
    # session has no speakers to name.
    ctx = _ctx(mode="dictation", naming=None, ws=ws)
    state = _state()

    cont = await _on_text(ctx, ws, state, _set_mapping_frame({"S1": "Alice"}), None)

    assert cont is True
    frames = ws.frames()
    assert len(frames) == 1
    assert frames[0]["type"] == "error"
    assert frames[0]["code"] == "bad_message"
    assert frames[0]["recoverable"] is True
    assert ctx.mapping_manual is False
    assert state.audit_writer.events == []
