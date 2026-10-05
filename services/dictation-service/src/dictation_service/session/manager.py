"""Per-process session registry + in-memory contexts; DB status mirrors ctx.state."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from auth import Claims

from .state import SessionState

logger = logging.getLogger(__name__)


@dataclass
class SessionContext:
    """Everything the session loop needs in one place."""

    session_id: UUID
    tenant_id: UUID
    user_id: UUID
    language: str
    vocabulary_hint: str  # Whisper initial_prompt; empty = none
    target_kind: str
    template_id: UUID | None
    template_text: str | None = None

    # Original capture surface ('browser' | 'mobile' | 'room_device'); a resume never overwrites.
    capture_source: str = "browser"
    device_name: str | None = None

    state: SessionState = SessionState.CREATING
    state_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    # Wire-level state
    ws: Any | None = None  # WebSocket — typed Any so we don't import starlette here
    expected_seq: int = 0
    received_seqs_hwm: int = -1  # high-water mark for dedup
    out_seq: int = 0  # server-emitted message seq

    # Audio buffer + decoder
    buffer: Any | None = None  # SessionAudioBuffer
    decoder: Any | None = None  # OpusDecoder

    # Windowing + inference
    last_partial_emit_ms: int = 0
    last_window_cursor_ms: int = 0
    finalized_segments: list[Any] = field(default_factory=list)  # list[Segment]
    windower: Any | None = None  # StreamingWindower; teardown paths flush provisional words
    # Serialises windower mutation: the end-of-session drain races the live tick loop.
    window_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    # Timing
    created_at: float = field(default_factory=time.monotonic)
    last_active_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    paused_at: float | None = None
    network_drop_count: int = 0

    # Auth
    claims: Claims | None = None
    token_exp_ts: int | None = None

    # Metrics accumulators
    partial_latencies_ms: list[int] = field(default_factory=list)
    final_latencies_ms: list[int] = field(default_factory=list)

    # Section-aware dictation
    template_doc: Any | None = None  # TemplateDoc (avoiding import cycle)
    active_section_id: str | None = None
    active_section_prompt: str | None = None

    # Conversation mode + protocol v2; diarization state survives an in-process resume.
    mode: str = "dictation"  # 'dictation' | 'conversation'
    protocol_version: int = 1
    bearer: str | None = None  # raw token; draft creation forwards the caller's identity
    capacity_weight: int = 1
    diarization: Any | None = None  # DiarizationStream (Any: torch-free import path)
    speaker_naming: Any | None = None  # SpeakerNaming (conversation only)
    mapping_manual: bool = False  # a SetSpeakerMapping arrived
    # Honesty metrics, counted on committed words only.
    unknown_speaker_words: int = 0
    labeled_speaker_words: int = 0
    pending_speaker_words: int = 0
    speaker_mapping_manual_sets: int = 0

    def touch(self) -> None:
        self.last_active_at = time.monotonic()

    def is_active(self) -> bool:
        return self.state == SessionState.ACTIVE


class SessionManager:
    """Thread-safe (asyncio-safe) registry of live sessions on this process."""

    def __init__(self, *, max_sessions: int) -> None:
        self._sessions: dict[UUID, SessionContext] = {}
        self._lock = asyncio.Lock()
        self._max_sessions = max_sessions
        # Scale-in drain (POST /internal/drain): admit nothing new; one-way by design.
        self._draining = False

    @property
    def draining(self) -> bool:
        return self._draining

    def begin_drain(self) -> None:
        self._draining = True
        logger.warning(
            "session_manager.draining",
            extra={"active": self.active_count, "total_weight": self.total_weight},
        )

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.state == SessionState.ACTIVE)

    @property
    def total_count(self) -> int:
        return len(self._sessions)

    @property
    def total_weight(self) -> int:
        """Mode-aware load; the cap compares weight, not headcount."""
        return sum(s.capacity_weight for s in self._sessions.values())

    def fits(self, weight: int) -> bool:
        if self._draining:
            return False
        return self.total_weight + weight <= self._max_sessions

    async def register(self, ctx: SessionContext) -> None:
        async with self._lock:
            if self._draining:
                # Same client semantics as gpu_full: reconnect lands on another pod.
                raise CapacityError("worker is draining for scale-in; no new sessions")
            if self.total_weight + ctx.capacity_weight > self._max_sessions:
                raise CapacityError(
                    f"worker at capacity (weight {self.total_weight}"
                    f"+{ctx.capacity_weight} > {self._max_sessions})"
                )
            if ctx.session_id in self._sessions:
                raise DuplicateSessionError(f"session_id {ctx.session_id} already attached")
            self._sessions[ctx.session_id] = ctx
            logger.info(
                "session.registered",
                extra={"session_id": str(ctx.session_id), "tenant_id": str(ctx.tenant_id)},
            )

    async def unregister(self, session_id: UUID) -> SessionContext | None:
        async with self._lock:
            ctx = self._sessions.pop(session_id, None)
            if ctx is not None:
                logger.info("session.unregistered", extra={"session_id": str(session_id)})
            return ctx

    def get(self, session_id: UUID) -> SessionContext | None:
        return self._sessions.get(session_id)

    def all(self) -> list[SessionContext]:
        return list(self._sessions.values())

    async def has_live_for(self, session_id: UUID) -> bool:
        """Single-tab guard. True iff a live WS is attached to this session."""
        ctx = self._sessions.get(session_id)
        return ctx is not None and ctx.ws is not None


class CapacityError(Exception):
    """Raised on register() when per-worker max is reached."""


class DuplicateSessionError(Exception):
    """Raised on register() when a session_id is already attached to a live ctx."""
