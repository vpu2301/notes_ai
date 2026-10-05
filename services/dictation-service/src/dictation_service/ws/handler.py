"""WebSocket session handler: start/resume, frame pump, windower ticks, finalize."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from typing import Any
from uuid import uuid4

from fastapi import WebSocketDisconnect

from audit import Severity
from db import tenant_connection

from .. import audit_kinds, metrics
from ..audio import (
    GapPolicy,
    OpusDecodeError,
    OpusDecoder,
    SessionAudioBuffer,
    decode_pcm_view,
    gap_decision,
)
from ..audio.gap import GapDecision
from ..config import settings
from ..diarization.engine import DiarizationUnavailableError
from ..diarization.mapping import SpeakerNaming
from ..domain import repository
from ..inference import StreamingWindower
from ..main_deps import auth_issuers
from ..notifications import emit_dictation_completed
from ..protocol import (
    PROTOCOL_VERSION_V1,
    PROTOCOL_VERSION_V2,
    AudioFrame,
    BadMessageError,
    EndSession,
    Error,
    ErrorCode,
    Final,
    FinalV2,
    Partial,
    PartialV2,
    Pause,
    RefreshToken,
    Resume,
    RetransmitRange,
    SessionStarted,
    SessionStartedV2,
    SessionTerminated,
    SetSpeakerMapping,
    SpeakerMappingUpdated,
    StartSession,
    StartSessionV2,
    SwitchSection,
    TokenTiming,
    WarningMessage,
    decode_binary,
    decode_text,
    encode_server,
)
from ..protocol.error_catalogue import is_recoverable
from ..session.finalize import finalize_session
from ..session.heartbeat import (
    heartbeat_loop,
    idle_watchdog,
    token_expiry_watchdog,
)
from ..session.manager import (
    CapacityError,
    DuplicateSessionError,
    SessionContext,
)
from ..session.resume import (
    evaluate_resume,
    evaluate_retransmit,
)
from ..session.state import SessionState, assert_transition
from ..ws.upgrade import UpgradeContext

logger = logging.getLogger(__name__)


async def run_session(
    websocket: Any,  # starlette WebSocket
    *,
    upgrade: UpgradeContext,
    state: Any,
) -> None:
    """Top-level coroutine after the upgrade. Always closes cleanly."""
    await websocket.accept(subprotocol=upgrade.subprotocol)

    ctx: SessionContext | None = None
    try:
        ctx = await _wait_for_start(websocket, upgrade, state)
        if ctx is None:
            return  # already closed
        await _run_loop(ctx, websocket, state)
    except WebSocketDisconnect:
        if ctx is not None:
            await _on_client_disconnect(ctx, state)
    except Exception as exc:  # noqa: BLE001
        logger.exception("session.unhandled", exc_info=exc)
        with suppress(Exception):
            await websocket.send_text(
                encode_server(
                    Error(code=ErrorCode.INTERNAL, detail="internal error", recoverable=False)
                )
            )
        if ctx is not None:
            await _on_failed(ctx, state, kind="internal", detail=str(exc))


async def _wait_for_start(
    websocket: Any,
    upgrade: UpgradeContext,
    state: Any,
) -> SessionContext | None:
    """Read the first text message; expect StartSession or close."""
    try:
        text = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=settings.ws_idle_close_after_no_session_s,
        )
    except TimeoutError:
        await _send_and_close(
            websocket,
            Error(code=ErrorCode.BAD_MESSAGE, detail="no start_session received"),
            protocol_version=upgrade.protocol_version,
        )
        return None

    try:
        msg = decode_text(text, upgrade.protocol_version)
    except BadMessageError as exc:
        await _send_and_close(
            websocket,
            Error(code=exc.code, detail=exc.detail, recoverable=is_recoverable(exc.code)),
            protocol_version=upgrade.protocol_version,
        )
        return None

    if not isinstance(msg, StartSession):
        await _send_and_close(
            websocket,
            Error(code=ErrorCode.BAD_MESSAGE, detail="expected start_session first"),
            protocol_version=upgrade.protocol_version,
        )
        return None

    if msg.resume_session_id is not None:
        return await _resume_session(websocket, upgrade, state, msg)
    return await _new_session(websocket, upgrade, state, msg)


# ── New session ──────────────────────────────────────────────────────


async def _new_session(
    websocket: Any,
    upgrade: UpgradeContext,
    state: Any,
    start: StartSession,
) -> SessionContext | None:
    # mode exists only on the v2 wire; v1 is always dictation.
    mode = start.mode if isinstance(start, StartSessionV2) else "dictation"
    weight = settings.conversation_session_weight if mode == "conversation" else 1

    # A conversation session runs two models, so it costs more slots.
    if not state.session_manager.fits(weight):
        metrics.session_drops.add(1, {"reason": "gpu_full"})
        await _send_and_close(
            websocket,
            Error(
                code=ErrorCode.GPU_FULL,
                detail="worker at session capacity; retry shortly",
                recoverable=True,
            ),
            ws_code=1013,  # try again later
            protocol_version=upgrade.protocol_version,
        )
        return None

    async with tenant_connection(state.app_pool, upgrade.claims.tid) as conn:
        active = await repository.count_active_for_tenant(conn, tenant_id=upgrade.claims.tid)
    if active >= settings.per_tenant_max_active_sessions:
        await _send_and_close(
            websocket,
            Error(
                code=ErrorCode.RATE_LIMITED,
                detail="tenant active-session cap reached",
                recoverable=True,
            ),
            protocol_version=upgrade.protocol_version,
        )
        return None

    # Diarizer must be loadable at start, never fail mid-meeting with unlabeled audio.
    if mode == "conversation":
        try:
            await state.diarization_engine.ensure_loaded()
        except DiarizationUnavailableError as exc:
            await _send_and_close(
                websocket,
                Error(code=ErrorCode.WORKER_FAILED, detail=str(exc), recoverable=True),
                ws_code=1013,
                protocol_version=upgrade.protocol_version,
            )
            return None

    vocabulary_hint = start.vocabulary_hint or settings.default_vocabulary_hint

    session_id = uuid4()
    ctx = SessionContext(
        session_id=session_id,
        tenant_id=upgrade.claims.tid,
        user_id=upgrade.claims.sub,
        language=start.language,
        vocabulary_hint=vocabulary_hint,
        target_kind=start.target_kind,
        capture_source=start.capture_source,
        device_name=start.device_name,
        template_id=start.template_id,
        claims=upgrade.claims,
        token_exp_ts=upgrade.claims.exp,
        mode=mode,
        protocol_version=upgrade.protocol_version,
        bearer=upgrade.bearer,
        capacity_weight=weight,
    )
    ctx.ws = websocket
    ctx.state = SessionState.ACTIVE
    ctx.started_at = time.monotonic()
    ctx.buffer = SessionAudioBuffer(session_id=session_id)
    ctx.decoder = OpusDecoder()
    if mode == "conversation":
        ctx.diarization = state.diarization_engine.new_stream()
        ctx.speaker_naming = SpeakerNaming()

    # Template fetch forwards the caller's own bearer (cross-service pattern).
    template_client = getattr(state, "template_client", None)
    s2s_bearer = upgrade.bearer
    if start.template_id is not None and template_client is not None and s2s_bearer:
        try:
            tpl = await template_client.fetch(template_id=start.template_id, bearer=s2s_bearer)
            if tpl is not None:
                ctx.template_doc = tpl
                if tpl.sections:
                    first = tpl.sections[0]
                    ctx.active_section_id = first.get("id")
                    ctx.active_section_prompt = first.get("asr_prompt")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "template_load.failed",
                extra={
                    "session_id": str(session_id),
                    "template_id": str(start.template_id),
                    "error_class": type(exc).__name__,
                },
            )

    try:
        await state.session_manager.register(ctx)
    except CapacityError:
        ctx.buffer.close()
        await _send_and_close(
            websocket,
            Error(code=ErrorCode.GPU_FULL, recoverable=True),
            ws_code=1013,
            protocol_version=upgrade.protocol_version,
        )
        return None
    except DuplicateSessionError:
        ctx.buffer.close()
        await _send_and_close(
            websocket,
            Error(code=ErrorCode.SESSION_NOT_FOUND, recoverable=False),
            protocol_version=upgrade.protocol_version,
        )
        return None

    async with tenant_connection(state.app_pool, ctx.tenant_id) as conn:
        await repository.insert_session(
            conn,
            session_id=session_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            language=ctx.language,
            target_kind=ctx.target_kind,
            template_id=ctx.template_id,
            worker_id=settings.worker_id,
            mode=ctx.mode,
            capture_source=ctx.capture_source,
            device_name=ctx.device_name,
        )

    started_payload: dict[str, Any] = {
        "language": ctx.language,
        "target_kind": ctx.target_kind,
        "mode": ctx.mode,
        "protocol_version": ctx.protocol_version,
        "capture_source": ctx.capture_source,
    }
    if ctx.device_name is not None:
        started_payload["device_name"] = ctx.device_name
    await state.audit_writer.write_event(
        tenant_id=ctx.tenant_id,
        kind=audit_kinds.SESSION_STARTED,
        actor_sub=ctx.user_id,
        target_kind="dictation_session",
        target_id=str(session_id),
        payload=started_payload,
        severity=Severity.INFO,
    )

    metrics.conversation_sessions.add(1, {"mode": ctx.mode})

    started_kwargs: dict[str, Any] = {
        "session_id": session_id,
        "resumed": False,
        "last_committed_seq": 0,
        "committed_audio_until_ms": 0,
        "server_time_ms": int(time.time() * 1000),
        "model": state.engine.model_name,
        "language": ctx.language,
    }
    if ctx.protocol_version == PROTOCOL_VERSION_V2:
        started = SessionStartedV2(**started_kwargs, mode=ctx.mode)  # type: ignore[arg-type]
    else:
        started = SessionStarted(**started_kwargs)  # type: ignore[assignment]
    await websocket.send_text(encode_server(started, ctx.protocol_version))
    return ctx


# ── Resume ────────────────────────────────────────────────────────────


async def _resume_session(
    websocket: Any,
    upgrade: UpgradeContext,
    state: Any,
    start: StartSession,
) -> SessionContext | None:
    sid = start.resume_session_id
    assert sid is not None
    live_attached = await state.session_manager.has_live_for(sid)
    async with tenant_connection(state.app_pool, upgrade.claims.tid) as conn:
        outcome = await evaluate_resume(
            conn,
            state.redis,
            session_id=sid,
            requesting_user=upgrade.claims.sub,
            requesting_tenant=upgrade.claims.tid,
            live_session_attached=live_attached,
        )
    if not outcome.allowed:
        # Uniform failure; never leak the precise reason.
        await _send_and_close(
            websocket,
            Error(
                code=ErrorCode.SESSION_NOT_FOUND,
                detail="session not found",
                recoverable=False,
            ),
            protocol_version=upgrade.protocol_version,
        )
        return None

    row = outcome.row
    assert row is not None
    ctx: SessionContext | None = state.session_manager.get(sid)
    if ctx is None:
        # In DB but no in-process context: worker restarted, buffer is gone.
        await _send_and_close(
            websocket,
            Error(
                code=ErrorCode.WORKER_FAILED,
                detail="worker restarted; recover via local buffer",
                recoverable=False,
            ),
            protocol_version=upgrade.protocol_version,
        )
        return None

    # A session is one wire version for life; a v1 tab must not get v2 frames.
    if ctx.protocol_version != upgrade.protocol_version:
        await _send_and_close(
            websocket,
            Error(
                code=ErrorCode.SESSION_NOT_FOUND,
                detail="session not found",
                recoverable=False,
            ),
            protocol_version=upgrade.protocol_version,
        )
        return None

    ctx.ws = websocket
    ctx.network_drop_count += 1
    ctx.state = SessionState.ACTIVE
    ctx.bearer = upgrade.bearer  # reconnects may carry a fresher token
    # capture_source/device_name describe the original capture; the resume frame's are ignored.
    ctx.touch()
    metrics.reconnects.add(1, {"worker_id": settings.worker_id, "mode": ctx.mode})

    await state.audit_writer.write_event(
        tenant_id=ctx.tenant_id,
        kind=audit_kinds.SESSION_RESUMED,
        actor_sub=ctx.user_id,
        target_kind="dictation_session",
        target_id=str(sid),
        payload={"network_drop_count": ctx.network_drop_count},
        severity=Severity.INFO,
    )

    resumed_kwargs: dict[str, Any] = {
        "session_id": sid,
        "resumed": True,
        "last_committed_seq": ctx.received_seqs_hwm + 1,
        "committed_audio_until_ms": ctx.buffer.total_ms if ctx.buffer else 0,
        "server_time_ms": int(time.time() * 1000),
        "model": state.engine.model_name,
        "language": ctx.language,
    }
    if ctx.protocol_version == PROTOCOL_VERSION_V2:
        resumed = SessionStartedV2(**resumed_kwargs, mode=ctx.mode)  # type: ignore[arg-type]
    else:
        resumed = SessionStarted(**resumed_kwargs)  # type: ignore[assignment]
    await websocket.send_text(encode_server(resumed, ctx.protocol_version))
    return ctx


# ── Main session loop ────────────────────────────────────────────────


async def _run_loop(ctx: SessionContext, websocket: Any, state: Any) -> None:
    windower = StreamingWindower(
        base_prompt=ctx.vocabulary_hint,
        language=ctx.language,
    )
    ctx.windower = windower  # finalize paths read it from ctx
    stop = asyncio.Event()

    async def _on_idle(_ctx: SessionContext) -> None:
        with suppress(Exception):
            await websocket.close(code=1011)

    hb_task = asyncio.create_task(heartbeat_loop(ctx))
    idle_task = asyncio.create_task(idle_watchdog(ctx, on_idle=_on_idle))
    tok_task = asyncio.create_task(token_expiry_watchdog(ctx))
    tick_task = asyncio.create_task(_window_loop(ctx, windower, state, stop))

    try:
        while True:
            try:
                msg = await websocket.receive()
            except WebSocketDisconnect:
                raise
            ctx.touch()

            # Starlette frame: 'type' plus either 'text' or 'bytes'.
            if "text" in msg and msg["text"] is not None:
                cont = await _on_text(ctx, websocket, state, msg["text"], windower)
                if not cont:
                    break
            elif "bytes" in msg and msg["bytes"] is not None:
                await _on_binary(ctx, websocket, state, msg["bytes"])
            elif msg.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(code=msg.get("code", 1006))
    finally:
        stop.set()
        for t in (hb_task, idle_task, tok_task, tick_task):
            t.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await t

        # Hard-cap finalize (also handled inline in _on_binary).
        if ctx.state == SessionState.ACTIVE and ctx.buffer is not None and _exceeds_hard_cap(ctx):
            await _finalize_normal(ctx, state, reason="cap_reached")


# ── Frame handlers ───────────────────────────────────────────────────


async def _on_text(
    ctx: SessionContext,
    websocket: Any,
    state: Any,
    text: str,
    windower: StreamingWindower,
) -> bool:
    """Process one text frame. Return False if the loop should exit."""
    try:
        msg = decode_text(text, ctx.protocol_version)
    except BadMessageError as exc:
        await websocket.send_text(
            encode_server(
                Error(
                    code=exc.code,
                    detail=exc.detail,
                    recoverable=is_recoverable(exc.code),
                )
            )
        )
        return True  # stay open

    if isinstance(msg, EndSession):
        await _finalize_normal(ctx, state, reason="normal")
        return False

    if isinstance(msg, Pause):
        if ctx.state != SessionState.ACTIVE:
            await websocket.send_text(
                encode_server(Error(code=ErrorCode.PAUSE_STATE_MISMATCH, recoverable=True))
            )
            return True
        await apply_pause(ctx, state)
        return True

    if isinstance(msg, Resume):
        if ctx.state != SessionState.PAUSED:
            await websocket.send_text(
                encode_server(Error(code=ErrorCode.PAUSE_STATE_MISMATCH, recoverable=True))
            )
            return True
        await apply_resume(ctx, state)
        return True

    if isinstance(msg, RetransmitRange):
        decision = evaluate_retransmit(
            from_seq=msg.from_seq,
            to_seq=msg.to_seq,
            hwm=ctx.received_seqs_hwm,
        )
        if decision.too_large:
            await websocket.send_text(
                encode_server(
                    Error(
                        code=ErrorCode.RETRANSMIT_TOO_LARGE,
                        detail=f"max {settings.retransmit_max_range_frames} frames",
                        recoverable=True,
                    )
                )
            )
        # Either way frames are accepted and deduped as they arrive.
        return True

    if isinstance(msg, SetSpeakerMapping):
        # Manual naming is authoritative from this moment.
        if ctx.mode != "conversation" or ctx.speaker_naming is None:
            await websocket.send_text(
                encode_server(
                    Error(
                        code=ErrorCode.BAD_MESSAGE,
                        detail="set_speaker_mapping is only valid in conversation mode",
                        recoverable=True,
                    ),
                    ctx.protocol_version,
                )
            )
            return True
        ctx.speaker_naming.set_names(dict(msg.mapping))
        ctx.mapping_manual = True
        ctx.speaker_mapping_manual_sets += 1
        metrics.speaker_mapping_updates.add(1, {"source": "manual"})
        await state.audit_writer.write_event(
            tenant_id=ctx.tenant_id,
            kind=audit_kinds.SPEAKER_MAPPING_MANUAL_SET,
            actor_sub=ctx.user_id,
            target_kind="dictation_session",
            target_id=str(ctx.session_id),
            payload={"mapping": dict(msg.mapping)},
            severity=Severity.INFO,
        )
        # No out_seq bump: SpeakerMappingUpdated carries no seq; a bump would gap the client's sequence.
        with suppress(Exception):
            await websocket.send_text(
                encode_server(
                    SpeakerMappingUpdated(
                        session_id=ctx.session_id,
                        mapping=ctx.speaker_naming.current.mapping,
                        confidence=1.0,
                        rationale="manual override",
                        manual=True,
                    ),
                    ctx.protocol_version,
                )
            )
        return True

    if isinstance(msg, SwitchSection):
        if ctx.template_doc is None:
            await websocket.send_text(
                encode_server(
                    Error(
                        code=ErrorCode.BAD_MESSAGE,
                        detail="no template loaded for this session",
                        recoverable=True,
                    )
                )
            )
            return True
        from ..integrations.template_client import section_prompt

        resolved = section_prompt(ctx.template_doc, msg.section_id)
        if resolved is None:
            await websocket.send_text(
                encode_server(
                    Error(
                        code=ErrorCode.BAD_MESSAGE,
                        detail=f"section {msg.section_id!r} not in template",
                        recoverable=True,
                    )
                )
            )
            return True
        new_prompt, new_section_name = resolved
        from_section = ctx.active_section_id
        ctx.active_section_id = msg.section_id
        ctx.active_section_prompt = new_prompt
        if windower is not None:
            windower.base_prompt = new_prompt
        await state.audit_writer.write_event(
            tenant_id=ctx.tenant_id,
            kind=audit_kinds.SECTION_SWITCHED,
            actor_sub=ctx.user_id,
            target_kind="dictation_session",
            target_id=str(ctx.session_id),
            payload={
                "from_section": from_section or "",
                "to_section": msg.section_id,
                "to_section_name": new_section_name,
                "reason": msg.reason,
            },
            severity=Severity.INFO,
        )
        return True

    if isinstance(msg, RefreshToken):
        from auth import verify_token

        try:
            new_claims = await verify_token(
                msg.token,
                jwks_cache=state.jwks_cache,
                issuers=auth_issuers(),  # same issuer list as the HTTP dependency
                clock_skew_seconds=settings.auth_clock_skew_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            await websocket.send_text(
                encode_server(
                    Error(
                        code=ErrorCode.AUTH_INVALID,
                        detail=f"refresh rejected: {type(exc).__name__}",
                        recoverable=False,
                    )
                )
            )
            return True
        # Must be the same user + tenant.
        if new_claims.sub != ctx.user_id or new_claims.tid != ctx.tenant_id:
            await websocket.send_text(
                encode_server(
                    Error(
                        code=ErrorCode.AUTH_INVALID,
                        detail="refresh subject/tenant mismatch",
                        recoverable=False,
                    )
                )
            )
            return True
        ctx.claims = new_claims
        ctx.token_exp_ts = new_claims.exp
        ctx.bearer = msg.token  # finalize-time draft creation uses the freshest token
        return True

    if isinstance(msg, StartSession):
        await websocket.send_text(
            encode_server(
                Error(
                    code=ErrorCode.BAD_MESSAGE,
                    detail="session already started",
                    recoverable=False,
                )
            )
        )
        return True

    return True


async def _on_binary(ctx: SessionContext, websocket: Any, state: Any, data: bytes) -> None:
    """Process one binary audio frame."""
    if ctx.state == SessionState.PAUSED:
        await websocket.send_text(
            encode_server(
                Error(
                    code=ErrorCode.PAUSE_STATE_MISMATCH,
                    detail="session paused; resume first",
                    recoverable=True,
                )
            )
        )
        return

    try:
        frame: AudioFrame = decode_binary(data)
    except BadMessageError as exc:
        await websocket.send_text(
            encode_server(Error(code=exc.code, detail=exc.detail, recoverable=False))
        )
        with suppress(Exception):
            await websocket.close(code=1003)
        return

    decision = gap_decision(ctx.expected_seq, frame.seq, policy=GapPolicy())
    if decision.decision == GapDecision.DUPLICATE:
        return  # silently drop
    if decision.decision == GapDecision.REQUEST_RETRANSMIT:
        await websocket.send_text(
            encode_server(
                Error(
                    code=ErrorCode.GAP_DETECTED,
                    detail=f"expected {ctx.expected_seq}, got {frame.seq}",
                    recoverable=True,
                )
            )
        )
        return
    if decision.decision == GapDecision.PAD_SILENCE and ctx.buffer is not None:
        ctx.buffer.insert_silence(decision.pad_samples)

    if ctx.decoder is None or ctx.buffer is None:
        return
    try:
        pcm = ctx.decoder.decode(frame.opus)
    except OpusDecodeError as exc:
        await websocket.send_text(
            encode_server(
                Error(
                    code=ErrorCode.AUDIO_DECODE_FAILED,
                    detail=exc.args[0] if exc.args else "decode failed",
                    recoverable=not exc.fatal,
                )
            )
        )
        if exc.fatal:
            await _on_failed(ctx, state, kind="worker_failed", detail="opus_decode")
            with suppress(Exception):
                await websocket.close(code=1011)
        return
    ctx.buffer.write(pcm)
    ctx.expected_seq = decision.next_expected_seq
    ctx.received_seqs_hwm = max(ctx.received_seqs_hwm, frame.seq)

    if _exceeds_hard_cap(ctx):
        await _finalize_normal(ctx, state, reason="cap_reached")
        with suppress(Exception):
            await websocket.close(code=1000)


# ── Background tasks ─────────────────────────────────────────────────

# Failed ticks in a row before the session is failed instead of "recording" nothing.
_MAX_CONSECUTIVE_TICK_FAILURES = 3


async def _window_loop(
    ctx: SessionContext,
    windower: StreamingWindower,
    state: Any,
    stop: asyncio.Event,
) -> None:
    """Tick the windower every N ms; emit partials + finals.

    This loop is the transcript: a bad tick is logged and skipped, repeated
    failures fail the session rather than silently transcribing nothing.
    """
    interval = settings.window_tick_interval_ms / 1000.0
    consecutive_failures = 0
    while not stop.is_set() and ctx.ws is not None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        if ctx.state != SessionState.ACTIVE or ctx.buffer is None:
            continue
        try:
            await _window_tick(ctx, windower, state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            consecutive_failures += 1
            logger.exception(
                "windower.tick_failed",
                extra={
                    "session_id": str(ctx.session_id),
                    "mode": ctx.mode,
                    "error_class": type(exc).__name__,
                    "consecutive": consecutive_failures,
                },
            )
            if consecutive_failures >= _MAX_CONSECUTIVE_TICK_FAILURES:
                await _on_failed(
                    ctx,
                    state,
                    kind="worker_failed",
                    detail=f"window loop failed {consecutive_failures}x: {type(exc).__name__}",
                )
                return
        else:
            consecutive_failures = 0


async def _drain_final_window(ctx: SessionContext, state: Any) -> None:
    """Force one window for the sub-hop audio tail. Best-effort: errors never block finalize."""
    windower = ctx.windower
    if windower is None or ctx.buffer is None:
        return
    try:
        await _window_tick(ctx, windower, state, force=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "windower.final_drain_failed",
            extra={"session_id": str(ctx.session_id), "error_class": type(exc).__name__},
        )


async def _window_tick(
    ctx: SessionContext,
    windower: StreamingWindower,
    state: Any,
    *,
    force: bool = False,
) -> None:
    """One windower tick: slice → inference (+ diarization) → emit."""
    if ctx.buffer is None:
        return
    async with ctx.window_lock:
        await _window_tick_locked(ctx, windower, state, force=force)


async def _window_tick_locked(
    ctx: SessionContext,
    windower: StreamingWindower,
    state: Any,
    *,
    force: bool = False,
) -> None:
    if ctx.buffer is None:
        return
    slice_ = windower.next_slice(buffer_total_ms=ctx.buffer.total_ms, force=force)
    if slice_ is None:
        return
    try:
        pcm = decode_pcm_view(ctx.buffer, slice_.start_ms, slice_.end_ms)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "windower.buffer_read_failed",
            extra={"session_id": str(ctx.session_id), "error": str(exc)},
        )
        return
    prompt = windower.build_prompt_for_next_window()
    t_window = time.monotonic()
    t0 = t_window
    try:
        window_result = await state.inference_queue.submit(
            pcm,
            language=ctx.language,
            # prev_text already carries base + tail; passing prompt too would
            # duplicate the initial_prompt (a Whisper hallucination trigger).
            prompt=None,
            prev_text=prompt,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "windower.inference_failed",
            extra={"session_id": str(ctx.session_id), "error": str(exc)},
        )
        return
    infer_seconds = time.monotonic() - t0
    mode_attrs = {"worker_id": settings.worker_id, "mode": ctx.mode}
    metrics.window_inference_ms.record(infer_seconds * 1000.0, mode_attrs)
    window_audio_seconds = max(0, slice_.end_ms - slice_.start_ms) / 1000.0
    if infer_seconds > 0:
        metrics.rtf.record(window_audio_seconds / infer_seconds, mode_attrs)
    tick = windower.integrate(
        window_segments=getattr(window_result, "segments", []),
        window_no_speech_prob=getattr(window_result, "no_speech_prob", 1.0),
        window_start_ms=slice_.start_ms,
        window_end_ms=slice_.end_ms,
        infer_seconds=infer_seconds,
        pcm_for_vad=pcm,
    )

    # Diarize in a thread; failure degrades to unlabeled words, text always wins.
    if ctx.mode == "conversation" and ctx.diarization is not None:
        try:
            await asyncio.to_thread(
                ctx.diarization.process_window,
                pcm,
                window_start_ms=slice_.start_ms,
            )
            metrics.diarization_window_ms.record(
                ctx.diarization.last_window_seconds * 1000.0,
                {"worker_id": settings.worker_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "diarization.window_failed",
                extra={"session_id": str(ctx.session_id), "error_class": type(exc).__name__},
            )
        # Inference + diarization: the sum must fit the tick budget.
        metrics.conversation_window_total_ms.record(
            (time.monotonic() - t_window) * 1000.0,
            {"worker_id": settings.worker_id},
        )

    await _emit_tick(ctx, tick)


def _wire_words(words: Any) -> list[TokenTiming]:
    """Project inference ``WordTiming`` onto wire ``TokenTiming``; pydantic v2 does not coerce across models."""
    return [
        TokenTiming(
            text=w.text,
            start_ms=w.start_ms,
            end_ms=w.end_ms,
            probability=w.probability,
        )
        for w in words
    ]


async def _emit_tick(ctx: SessionContext, tick: Any) -> None:
    """Serialize windower output to the wire."""
    if ctx.ws is None:
        return
    if tick.boundary_uncertainty > settings.aligner_boundary_uncertainty_threshold:
        with suppress(Exception):
            await ctx.ws.send_text(
                encode_server(
                    WarningMessage(
                        session_id=ctx.session_id,
                        code="low_confidence",
                        detail=f"boundary={tick.boundary_uncertainty:.2f}",
                    ),
                    ctx.protocol_version,
                )
            )
    v2 = ctx.protocol_version == PROTOCOL_VERSION_V2
    hint = _current_mapping_hint(ctx)
    if tick.new_partial is not None:
        ctx.out_seq += 1
        partial_age_ms = max(0, ctx.buffer.total_ms - tick.new_partial.end_ms) if ctx.buffer else 0
        ctx.partial_latencies_ms.append(partial_age_ms)
        metrics.partial_latency_ms.record(
            partial_age_ms, {"worker_id": settings.worker_id, "mode": ctx.mode}
        )
        partial_kwargs: dict[str, Any] = {
            "session_id": ctx.session_id,
            "seq": ctx.out_seq,
            "text": tick.new_partial.text,
            "start_ms": tick.new_partial.start_ms,
            "end_ms": tick.new_partial.end_ms,
            "words": _wire_words(tick.new_partial.words),
            "avg_confidence": tick.new_partial.avg_confidence,
        }
        if v2:
            # Partials re-emit every tick, so only committed words are counted.
            speaker, speaker_conf = _attribute_segment(ctx, tick.new_partial, count=False)
            message: Any = PartialV2(
                **partial_kwargs,
                speaker=speaker,
                speaker_confidence=speaker_conf,
                speaker_mapping_hint=hint,
            )
        else:
            message = Partial(**partial_kwargs)
        with suppress(Exception):
            await ctx.ws.send_text(encode_server(message, ctx.protocol_version))
    for seg in tick.new_finals:
        ctx.out_seq += 1
        final_age_ms = max(0, ctx.buffer.total_ms - seg.end_ms) if ctx.buffer else 0
        ctx.final_latencies_ms.append(final_age_ms)
        metrics.final_latency_ms.record(
            final_age_ms, {"worker_id": settings.worker_id, "mode": ctx.mode}
        )
        ctx.finalized_segments.append(seg)
        final_kwargs: dict[str, Any] = {
            "session_id": ctx.session_id,
            "seq": ctx.out_seq,
            "text": seg.text,
            "start_ms": seg.start_ms,
            "end_ms": seg.end_ms,
            "words": _wire_words(seg.words),
            "avg_confidence": seg.avg_confidence,
            "voice_command": None,
        }
        if v2:
            speaker, speaker_conf = _attribute_segment(ctx, seg, count=True)
            final_message: Any = FinalV2(
                **final_kwargs,
                speaker=speaker,
                speaker_confidence=speaker_conf,
                speaker_mapping_hint=hint,
            )
        else:
            final_message = Final(**final_kwargs)
        with suppress(Exception):
            await ctx.ws.send_text(encode_server(final_message, ctx.protocol_version))


def _attribute_segment(
    ctx: SessionContext, seg: Any, *, count: bool
) -> tuple[str | None, float | None]:
    """Speaker proposal for a segment; None while labels trail the text. ``count`` gates the word metrics."""
    if ctx.diarization is None:
        return None, None
    speaker, conf = ctx.diarization.attribute(int(seg.start_ms), int(seg.end_ms))
    if count:
        n_words = len(getattr(seg, "words", []) or [])
        outcome = "unknown" if speaker == "UNKNOWN" else ("labeled" if speaker else "pending")
        if outcome == "unknown":
            ctx.unknown_speaker_words += n_words
        elif outcome == "labeled":
            ctx.labeled_speaker_words += n_words
        else:
            ctx.pending_speaker_words += n_words
        metrics.conversation_words.add(
            n_words, {"outcome": outcome, "tenant_id": str(ctx.tenant_id)}
        )
    return speaker, conf


def _current_mapping_hint(ctx: SessionContext) -> dict[str, Any] | None:
    """Label → display-name mapping on every v2 frame; neutral defaults until the client names speakers."""
    if ctx.speaker_naming is None:
        return None
    return dict(ctx.speaker_naming.current.mapping)


# ── Closure paths ────────────────────────────────────────────────────


async def _send_and_close(
    websocket: Any,
    error: Error,
    *,
    ws_code: int = 1008,
    protocol_version: int = PROTOCOL_VERSION_V1,
) -> None:
    # Encode at the negotiated version so a future v2-only Error field cannot vanish.
    with suppress(Exception):
        await websocket.send_text(encode_server(error, protocol_version))
    with suppress(Exception):
        await websocket.close(code=ws_code)


def _exceeds_hard_cap(ctx: SessionContext) -> bool:
    if ctx.buffer is None:
        return False
    return bool(ctx.buffer.total_ms >= settings.session_hard_cap_minutes * 60 * 1000)


async def _finalize_normal(ctx: SessionContext, state: Any, *, reason: str) -> None:
    # Must precede finalize_session, which only serialises what is already committed.
    await _drain_final_window(ctx, state)
    try:
        result = await finalize_session(
            ctx=ctx,
            app_pool=state.app_pool,
            audit_writer=state.audit_writer,
            audio_store=state.audio_store,
            envelope=state.envelope,
            reason=reason,
            purge_audio=settings.demo_audio_purge_on_finalize,
            nlp_client=getattr(state, "nlp_client", None),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("finalize.failed", exc_info=exc)
        await _on_failed(ctx, state, kind="internal", detail=f"finalize: {exc}")
        return

    # Completion paths only: failure/abandon never draft.
    if ctx.mode == "conversation":
        from ..session.draft import create_conversation_draft  # avoid import cycle

        await create_conversation_draft(ctx, state, finalize_result=result)

    # Here, not in finalize_session: failure/abandon share the finalizer but must not emit completion.
    await emit_dictation_completed(
        state.redis,
        tenant_id=ctx.tenant_id,
        session_id=ctx.session_id,
        user_id=ctx.user_id,
        duration_ms=result.duration_ms,
        segments=result.transcript_segments,
    )

    if ctx.ws is not None:
        with suppress(Exception):
            await ctx.ws.send_text(
                encode_server(
                    SessionTerminated(
                        session_id=ctx.session_id,
                        reason=reason,
                        finalized_audio_file_id=result.audio_file_id,
                    )
                )
            )
        with suppress(Exception):
            await ctx.ws.close(code=1000)
    await state.session_manager.unregister(ctx.session_id)


async def apply_pause(ctx: SessionContext, state: Any) -> None:
    """active → paused, persisted to the DB (other processes read status from there)."""
    assert_transition(ctx.state, SessionState.PAUSED)
    ctx.state = SessionState.PAUSED
    ctx.paused_at = time.monotonic()
    async with tenant_connection(state.app_pool, ctx.tenant_id) as conn:
        await repository.update_status(
            conn, session_id=ctx.session_id, new_status=SessionState.PAUSED
        )


async def apply_resume(ctx: SessionContext, state: Any) -> None:
    """paused → active, persisted. Mirror of :func:`apply_pause`."""
    assert_transition(ctx.state, SessionState.ACTIVE)
    ctx.state = SessionState.ACTIVE
    ctx.paused_at = None
    async with tenant_connection(state.app_pool, ctx.tenant_id) as conn:
        await repository.update_status(
            conn, session_id=ctx.session_id, new_status=SessionState.ACTIVE
        )


async def _on_client_disconnect(ctx: SessionContext, state: Any) -> None:
    """Move to reconnecting; the 30-min abandon timer takes it from there."""
    if ctx.state in {SessionState.FINALIZED, SessionState.ABANDONED, SessionState.FAILED}:
        return
    with suppress(Exception):
        assert_transition(ctx.state, SessionState.RECONNECTING)
    ctx.state = SessionState.RECONNECTING
    ctx.ws = None
    async with tenant_connection(state.app_pool, ctx.tenant_id) as conn:
        await repository.update_status(
            conn,
            session_id=ctx.session_id,
            new_status=SessionState.RECONNECTING,
        )
    asyncio.create_task(_abandon_after_idle(ctx, state))


async def _abandon_after_idle(ctx: SessionContext, state: Any) -> None:
    timeout = settings.session_idle_abandon_minutes * 60
    while True:
        if ctx.state != SessionState.RECONNECTING:
            return  # resumed or finalized
        elapsed = time.monotonic() - ctx.last_active_at
        if elapsed >= timeout:
            break
        await asyncio.sleep(min(30.0, timeout - elapsed))
    if ctx.state != SessionState.RECONNECTING:
        return
    ctx.state = SessionState.ABANDONED
    async with tenant_connection(state.app_pool, ctx.tenant_id) as conn:
        await repository.update_status(
            conn, session_id=ctx.session_id, new_status=SessionState.ABANDONED
        )
    await state.audit_writer.write_event(
        tenant_id=ctx.tenant_id,
        kind=audit_kinds.SESSION_ABANDONED,
        actor_sub=ctx.user_id,
        target_kind="dictation_session",
        target_id=str(ctx.session_id),
        payload={"idle_minutes": settings.session_idle_abandon_minutes},
        severity=Severity.INFO,
    )
    if ctx.buffer is not None:
        ctx.buffer.close()
        ctx.buffer = None
    await state.session_manager.unregister(ctx.session_id)


async def _on_failed(ctx: SessionContext, state: Any, *, kind: str, detail: str) -> None:
    ctx.state = SessionState.FAILED
    async with tenant_connection(state.app_pool, ctx.tenant_id) as conn:
        await repository.update_status(
            conn,
            session_id=ctx.session_id,
            new_status=SessionState.FAILED,
            error_kind=kind,
            error_detail=detail[:1024],
        )
    await state.audit_writer.write_event(
        tenant_id=ctx.tenant_id,
        kind=audit_kinds.SESSION_FAILED,
        actor_sub=ctx.user_id,
        target_kind="dictation_session",
        target_id=str(ctx.session_id),
        payload={"reason": kind, "detail": detail[:200]},
        severity=Severity.ERROR,
    )
    if ctx.buffer is not None:
        ctx.buffer.close()
        ctx.buffer = None
    await state.session_manager.unregister(ctx.session_id)
