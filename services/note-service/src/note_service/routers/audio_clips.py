"""POST /v1/audio-clips + GET /v1/audio-clips/{id} — replay clip pipeline.

ADR-0037: fetch the encrypted object, decrypt whole (GCM has no range mode),
slice, encode Ogg/Opus, store encrypted in the ephemeral clips bucket, answer
with a tokenised stream URL. Clips are derivatives (Redis TTL + bucket ILM).
410 + problem code when the audio cannot be served; caps on span and per-user rate.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import ReadPurpose
from storage import ObjectNotFoundError

from .. import audit_kinds
from ..config import settings
from ..deps import current_user, get_state, requires
from ..domain import access, audio_slicer
from ..domain import audio_clips as clips
from ..domain import notes_repository as repo
from .notes_versions import _enforce_read_purpose

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/audio-clips", tags=["audio-clips"])


class CreateClipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Note-anchored: the purpose gate and author check live on the note.
    note_id: UUID
    start_ms: int
    end_ms: int


class CreateClipResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: UUID
    clip_url: str
    expires_at_unix: int


def _gone(exc: clips.AudioUnavailableError) -> HTTPException:
    return HTTPException(
        status.HTTP_410_GONE,
        detail={
            "type": f"urn:mdx:note:audio:{exc.code}",
            "title": "Recording not available",
            "status": 410,
            "code": exc.code,
            "detail": exc.detail,
        },
    )


@router.post("", response_model=CreateClipResponse)
async def create_clip(
    body: CreateClipRequest,
    claims: Annotated[Claims, Depends(current_user)],
    purpose: Annotated[
        ReadPurpose | None, Query(description="Required for non-author reads.")
    ] = None,
) -> CreateClipResponse:
    state = get_state()
    # Same permission as every single-note content surface; checked
    # explicitly because note_id arrives in the body, not the path.
    await requires("note.read", "note")(claims)

    span_ms = body.end_ms - body.start_ms
    if body.start_ms < 0 or span_ms <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid ms range")
    if span_ms > settings.clip_max_span_ms:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"span exceeds {settings.clip_max_span_ms} ms — replay is review, not export",
        )

    allowed, retry_after = await state.clip_rate_limiter.check(user_id=claims.sub)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="clip rate limit reached",
            headers={"Retry-After": str(retry_after)},
        )

    started = time.perf_counter()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        # A private note the caller was not given is a 404.
        note = access.require_view(await repo.fetch_note(conn, note_id=body.note_id), claims)
        is_author = _enforce_read_purpose(note, claims, purpose)
        try:
            source = await clips.resolve_audio_source(conn, note_id=body.note_id)
        except clips.AudioUnavailableError as exc:
            state.clips_created_metric.add(1, {"source_kind": "unknown", "outcome": exc.code})
            raise _gone(exc) from None

    # The range must lie inside the window that survived the tmpfs ring.
    if body.start_ms < source.retained_from_ms:
        state.clips_created_metric.add(
            1, {"source_kind": source.kind, "outcome": "audio_partially_retained"}
        )
        raise _gone(
            clips.AudioUnavailableError(
                "audio_partially_retained",
                f"the session was truncated — audio before "
                f"{source.retained_from_ms} ms is not retained",
            )
        )

    try:
        encrypted_owner_aad = source.aad
        raw = await state.audio_store.get(
            key=source.object_key, tenant_id=claims.tid, aad=encrypted_owner_aad
        )
    except ObjectNotFoundError:
        state.clips_created_metric.add(1, {"source_kind": source.kind, "outcome": "audio_erased"})
        raise _gone(
            clips.AudioUnavailableError(
                "audio_erased", "the recording object has been deleted (retention/erasure)"
            )
        ) from None

    try:
        if source.mime_type == "audio/wav":
            pcm = audio_slicer.wav_to_pcm(raw)
        else:
            pcm = await audio_slicer.decode_to_pcm(raw, ffmpeg_path=settings.ffmpeg_path)
        pcm_slice = audio_slicer.slice_pcm(
            pcm,
            start_ms=body.start_ms - source.retained_from_ms,
            end_ms=body.end_ms - source.retained_from_ms,
            pad_ms=settings.clip_pad_ms,
        )
        opus = await audio_slicer.encode_opus(pcm_slice, ffmpeg_path=settings.ffmpeg_path)
    except audio_slicer.AudioClipError as exc:
        logger.warning("audio_clip.pipeline_failed: %s", exc)
        state.clips_created_metric.add(1, {"source_kind": source.kind, "outcome": "pipeline_error"})
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="clip pipeline failed") from exc

    clip_id = uuid4()
    object_key = f"clips/{claims.tid}/{clip_id}.ogg.enc"
    await state.clips_store.put(
        key=object_key, plaintext=opus, tenant_id=claims.tid, aad=clip_id.bytes
    )
    await clips.register_clip(
        state.redis,
        clip_id=clip_id,
        tenant_id=claims.tid,
        note_id=body.note_id,
        object_key=object_key,
        ttl_seconds=settings.clip_token_ttl_seconds,
    )
    token, exp_unix = clips.mint_clip_token(
        settings.clip_token_hmac_key_hex,
        tenant_id=claims.tid,
        clip_id=clip_id,
        ttl_seconds=settings.clip_token_ttl_seconds,
    )

    state.clip_pipeline_latency_metric.record((time.perf_counter() - started) * 1000.0)
    state.clips_created_metric.add(1, {"source_kind": source.kind, "outcome": "created"})
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=audit_kinds.NOTE_AUDIO_REPLAYED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=body.note_id,
        payload={
            "clip_id": str(clip_id),
            "source_kind": source.kind,
            "start_ms": body.start_ms,
            "end_ms": body.end_ms,
            "purpose": purpose.value if purpose else "author",
            "is_author": is_author,
        },
        severity=Severity.INFO,
    )

    return CreateClipResponse(
        clip_id=clip_id,
        clip_url=f"/v1/audio-clips/{clip_id}?t={token}",
        expires_at_unix=exp_unix,
    )


@router.get("/{clip_id}")
async def stream_clip(
    clip_id: UUID,
    claims: Annotated[Claims, Depends(current_user)],
    t: Annotated[str, Query(description="Download token from clip creation.")],
) -> Response:
    """Authenticated decrypt-and-stream (the DSAR download idiom): the
    token narrows the window; it never replaces authentication."""
    state = get_state()
    if not clips.verify_clip_token(
        settings.clip_token_hmac_key_hex, tenant_id=claims.tid, clip_id=clip_id, token=t
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "clip_link_expired", "detail": "request a fresh clip"},
        )
    entry = await clips.lookup_clip(state.redis, clip_id=clip_id)
    if entry is None or entry.get("tenant_id") != str(claims.tid):
        raise HTTPException(
            status.HTTP_410_GONE,
            detail={"code": "clip_expired", "detail": "clips are ephemeral — request a fresh one"},
        )
    try:
        opus = await state.clips_store.get(
            key=entry["key"], tenant_id=claims.tid, aad=clip_id.bytes
        )
    except ObjectNotFoundError:
        raise HTTPException(
            status.HTTP_410_GONE,
            detail={"code": "clip_expired", "detail": "clips are ephemeral — request a fresh one"},
        ) from None
    return Response(
        content=opus,
        media_type="audio/ogg",
        headers={"Cache-Control": "private, no-store"},
    )
