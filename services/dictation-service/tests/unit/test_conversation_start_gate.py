"""Conversation (meeting) mode start behaviour in ``_new_session`` (pure).

Conversation mode has no precondition beyond auth: a v2 client asks for
``mode: "conversation"`` and gets a weighted session with a diarization
stream and neutral speaker naming. The only start-time gate left is the
diarizer itself — it must be loadable, or the start fails loudly.
Dictation mode must be entirely unaffected.

Everything below the handler is faked: ``tenant_connection`` is replaced
with an async CM over a dummy connection and the domain readers
(``repository.count_active_for_tenant``, ``repository.insert_session``)
are monkeypatched on their own modules. The tmpfs ring buffer and the
Opus decoder are stubbed so no OS resources are touched.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from auth import Claims
from dictation_service import audit_kinds
from dictation_service.diarization.engine import DiarizationUnavailableError
from dictation_service.domain import repository as repository_mod
from dictation_service.protocol.messages import StartSession, StartSessionV2
from dictation_service.session.manager import SessionManager
from dictation_service.ws import handler as handler_mod
from dictation_service.ws.handler import _new_session
from dictation_service.ws.upgrade import UpgradeContext

TENANT_ID = uuid4()
USER_ID = uuid4()


# ── Fakes ────────────────────────────────────────────────────────────


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed_with: list[int] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int = 1000) -> None:
        self.closed_with.append(code)

    def frames(self) -> list[dict[str, Any]]:
        return [json.loads(t) for t in self.sent]


class _FakeAuditWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)

    def kinds(self) -> list[str]:
        return [e["kind"] for e in self.events]

    def by_kind(self, kind: str) -> dict[str, Any]:
        matches = [e for e in self.events if e["kind"] == kind]
        assert len(matches) == 1, f"expected exactly one {kind}, got {len(matches)}"
        return matches[0]


class _FakeDiarizationStream:
    segments: list[Any] = []

    def attribute(self, start_ms: int, end_ms: int) -> tuple[str | None, float | None]:
        return None, None


class _FakeDiarizationEngine:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.raises = raises
        self.ensure_loaded_calls = 0
        self.new_stream_calls = 0

    async def ensure_loaded(self) -> None:
        self.ensure_loaded_calls += 1
        if self.raises is not None:
            raise self.raises

    def new_stream(self) -> _FakeDiarizationStream:
        self.new_stream_calls += 1
        return _FakeDiarizationStream()


class _FakeBuffer:
    total_ms = 0

    def __init__(self, *, session_id: UUID) -> None:
        self.session_id = session_id
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Calls:
    """Counters for the monkeypatched domain readers."""

    def __init__(self) -> None:
        self.count_active = 0
        self.inserted: list[dict[str, Any]] = []


def _claims() -> Claims:
    now = int(time.time())
    return Claims(
        sub=USER_ID,
        tid=TENANT_ID,
        roles=["member"],
        sid="sess-1",
        iss="https://kc.example/realms/notes",
        aud="mdx-api",
        exp=now + 3600,
        iat=now,
    )


def _upgrade(*, protocol_version: int) -> UpgradeContext:
    return UpgradeContext(
        claims=_claims(),
        subprotocol=("dictation.v2" if protocol_version == 2 else "dictation.v1"),
        client_ip="127.0.0.1",
        origin=None,
        protocol_version=protocol_version,
        bearer="tok",
    )


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    active_sessions: int = 0,
    engine_raises: Exception | None = None,
) -> tuple[SimpleNamespace, _FakeWebSocket, _Calls]:
    calls = _Calls()

    @asynccontextmanager
    async def _fake_tenant_connection(_pool: Any, _tenant_id: UUID) -> Any:
        yield SimpleNamespace()

    async def _count_active(_conn: Any, *, tenant_id: UUID) -> int:
        calls.count_active += 1
        return active_sessions

    async def _insert_session(_conn: Any, **kwargs: Any) -> None:
        calls.inserted.append(kwargs)

    monkeypatch.setattr(handler_mod, "tenant_connection", _fake_tenant_connection)
    monkeypatch.setattr(repository_mod, "count_active_for_tenant", _count_active)
    monkeypatch.setattr(repository_mod, "insert_session", _insert_session)
    monkeypatch.setattr(handler_mod, "SessionAudioBuffer", _FakeBuffer)
    monkeypatch.setattr(handler_mod, "OpusDecoder", lambda: SimpleNamespace())

    state = SimpleNamespace(
        app_pool=SimpleNamespace(),
        session_manager=SessionManager(max_sessions=4),
        audit_writer=_FakeAuditWriter(),
        diarization_engine=_FakeDiarizationEngine(raises=engine_raises),
        engine=SimpleNamespace(model_name="large-v3"),
        template_client=None,
    )
    return state, _FakeWebSocket(), calls


def _start_v2(*, mode: str = "conversation", vocabulary_hint: str = "") -> StartSessionV2:
    return StartSessionV2(
        language="uk",
        mode=mode,
        vocabulary_hint=vocabulary_hint,
    )


# ── a. conversation starts with no precondition beyond auth ──────────


async def test_conversation_starts_a_weighted_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, ws, calls = _wire(monkeypatch)

    ctx = await _new_session(ws, _upgrade(protocol_version=2), state, _start_v2())

    assert ctx is not None
    assert ctx.mode == "conversation"
    assert ctx.protocol_version == 2
    assert ctx.bearer == "tok"
    assert ctx.capacity_weight == 2
    assert ctx.diarization is not None
    assert ctx.speaker_naming is not None
    assert ctx.mapping_manual is False

    # Registered, and it costs two slots.
    assert state.session_manager.get(ctx.session_id) is ctx
    assert state.session_manager.total_weight == 2
    assert state.session_manager.total_count == 1

    # Diarizer was proven loadable before any audio was accepted.
    assert state.diarization_engine.ensure_loaded_calls == 1
    assert state.diarization_engine.new_stream_calls == 1

    assert calls.inserted and calls.inserted[0]["mode"] == "conversation"

    started = ws.frames()[-1]
    assert started["type"] == "session_started"
    assert started["protocol_version"] == 2
    assert started["mode"] == "conversation"
    assert started["session_id"] == str(ctx.session_id)
    assert started["model"] == "large-v3"
    assert ws.closed_with == []

    audit = state.audit_writer.by_kind(audit_kinds.SESSION_STARTED)
    assert audit["payload"]["mode"] == "conversation"
    assert audit["payload"]["protocol_version"] == 2


# ── b. vocabulary hint reaches the session context ───────────────────


async def test_vocabulary_hint_lands_on_the_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, ws, _calls = _wire(monkeypatch)

    ctx = await _new_session(
        ws,
        _upgrade(protocol_version=2),
        state,
        _start_v2(mode="dictation", vocabulary_hint="Klarnote OKR roadmap"),
    )

    assert ctx is not None
    assert ctx.vocabulary_hint == "Klarnote OKR roadmap"


async def test_empty_hint_falls_back_to_the_config_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dictation_service.config import settings

    state, ws, _calls = _wire(monkeypatch)
    monkeypatch.setattr(settings, "default_vocabulary_hint", "team glossary")

    ctx = await _new_session(ws, _upgrade(protocol_version=1), state, StartSession(language="uk"))

    assert ctx is not None
    assert ctx.vocabulary_hint == "team glossary"


# ── c. dictation is untouched ────────────────────────────────────────


async def test_v1_dictation_start_is_weight_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, ws, calls = _wire(monkeypatch)

    ctx = await _new_session(
        ws,
        _upgrade(protocol_version=1),
        state,
        StartSession(language="uk"),
    )

    assert ctx is not None
    assert ctx.mode == "dictation"
    assert ctx.capacity_weight == 1
    assert ctx.diarization is None
    assert ctx.speaker_naming is None
    assert state.session_manager.total_weight == 1
    assert state.diarization_engine.ensure_loaded_calls == 0

    started = ws.frames()[-1]
    assert started["type"] == "session_started"
    assert started["protocol_version"] == 1
    assert "mode" not in started  # v1 wire stays byte-stable


async def test_v2_dictation_mode_is_weight_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, ws, _calls = _wire(monkeypatch)

    ctx = await _new_session(
        ws,
        _upgrade(protocol_version=2),
        state,
        _start_v2(mode="dictation"),
    )

    assert ctx is not None
    assert ctx.mode == "dictation"
    assert ctx.capacity_weight == 1
    assert ws.frames()[-1]["mode"] == "dictation"


# ── d. diarizer unavailable ──────────────────────────────────────────


async def test_unloadable_diarizer_fails_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, ws, _calls = _wire(
        monkeypatch,
        engine_raises=DiarizationUnavailableError("ecapa weights missing"),
    )

    ctx = await _new_session(ws, _upgrade(protocol_version=2), state, _start_v2())

    assert ctx is None
    frame = ws.frames()[-1]
    assert frame["type"] == "error"
    assert frame["code"] == "worker_failed"
    assert frame["recoverable"] is True
    assert "ecapa weights missing" in frame["detail"]
    assert ws.closed_with == [1013]
    assert state.session_manager.total_weight == 0
