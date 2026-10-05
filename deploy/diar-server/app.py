"""diar-server: the worker's ``PyannoteDiarizer`` as an endpoint (ADR-0052 shape B),
reached through ``diarization.HttpDiarizer``. No storage, no identifiers, no
embeddings out, no text; logs carry timings and counts only. Bearer
``MDX_DIAR_SERVER_TOKEN``; refuses to start without one unless
``MDX_DIAR_SERVER_ALLOW_ANONYMOUS=1``.

    uvicorn app:app --host 0.0.0.0 --port 8081
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.formparsers import MultiPartParser

from diarization import (
    DiarizationHints,
    InvalidHintsError,
    PyannoteDiarizer,
    RosterGuardConfig,
    audio_seconds,
    decode_audio,
    to_payload,
)

logger = logging.getLogger("diar_server")

MODEL_DIR = os.environ.get("MDX_DIAR_V2_MODEL_DIR", "/opt/models/pyannote-community-1")
MODEL_ID = os.environ.get("MDX_DIAR_MODEL_ID", "pyannote-community-1")
DEVICE = os.environ.get("MDX_DIAR_DEVICE", "cuda")
BATCH_SIZE = int(os.environ.get("MDX_DIAR_V2_BATCH", "32"))
TOKEN = os.environ.get("MDX_DIAR_SERVER_TOKEN", "")
ALLOW_ANONYMOUS = os.environ.get("MDX_DIAR_SERVER_ALLOW_ANONYMOUS", "") == "1"
# Own header because a managed endpoint's gateway consumes `Authorization`;
# `Authorization` is still accepted for a bare container.
TOKEN_HEADER = "x-mdx-diar-token"
# One pass at a time: the Pipeline object is not documented as thread-safe.
MAX_CONCURRENT = max(1, int(os.environ.get("MDX_DIAR_MAX_CONCURRENT", "1")))
# 2 h at 16 kHz float32 is ~460 MB; a compressed cap alone would not bound it.
MAX_AUDIO_SECONDS = float(os.environ.get("MDX_DIAR_MAX_AUDIO_SECONDS", "7500"))
# The worker rejects longer recordings first; a bigger body is a bug or abuse.
MAX_UPLOAD_BYTES = int(os.environ.get("MDX_DIAR_MAX_UPLOAD_BYTES", str(300 * 1024 * 1024)))
# Starlette spools a multipart part to a TEMP FILE above this size; raised
# past the body cap so the caller's audio never touches disk.
MultiPartParser.spool_max_size = MAX_UPLOAD_BYTES + (1 << 20)
# pyannote's own guards, mirrored from the worker image.
PIN_ENVIRON = {"PYANNOTE_METRICS_ENABLED": "false", "HF_HUB_OFFLINE": "1"}
HEALTH_ROUTE = "/health"


def _pin_environment() -> None:
    """Telemetry off and hub offline before pyannote is ever imported."""
    for key, value in PIN_ENVIRON.items():
        os.environ[key] = value


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not TOKEN and not ALLOW_ANONYMOUS:
        raise RuntimeError(
            "MDX_DIAR_SERVER_TOKEN is empty; set it, or "
            "MDX_DIAR_SERVER_ALLOW_ANONYMOUS=1 for a local dev server"
        )
    if DEVICE == "cpu" and os.environ.get("MDX_DIAR_ALLOW_CPU") != "1":
        # CPU runs 0.64-0.85x audio: recordings over ~70 s would time out and
        # be retried, which is worse than refusing to start.
        raise RuntimeError(
            "MDX_DIAR_DEVICE=cpu cannot meet the latency budget (ADR-0052); "
            "use cuda/mps, or set MDX_DIAR_ALLOW_CPU=1 deliberately"
        )
    _pin_environment()
    app.state.slots = asyncio.Semaphore(MAX_CONCURRENT)
    app.state.diarizer = PyannoteDiarizer(
        model_dir=MODEL_DIR,
        environ=dict(os.environ),
        device=DEVICE,
        pins=_pins(),
        model_repo=os.environ.get("MDX_DIAR_V2_MODEL_REPO", ""),
        model_revision=os.environ.get("MDX_DIAR_V2_MODEL_REVISION", ""),
        batch_size=BATCH_SIZE,
        # The floor is the caller's policy and travels with each request.
        roster=RosterGuardConfig(min_speaker_speech_ms=0, min_speaker_share=0.0),
    )
    yield


def _pins() -> dict[str, str]:
    raw = os.environ.get("MDX_DIAR_V2_PINS", "").strip()
    if not raw:
        return {}
    pins = json.loads(raw)
    if not isinstance(pins, dict):
        raise RuntimeError("MDX_DIAR_V2_PINS must be a JSON object of filename → sha256")
    return {str(k): str(v) for k, v in pins.items() if v}


app = FastAPI(title="diar-server", lifespan=lifespan, docs_url=None, redoc_url=None)


def _authenticated(headers: Any) -> bool:
    """Constant-time, byte-wise token check (a non-ASCII token is a refusal, not a 500)."""
    if not TOKEN:
        return ALLOW_ANONYMOUS
    presented = headers.get(TOKEN_HEADER) or ""
    if not presented:
        authorization = headers.get("authorization") or ""
        if authorization.lower().startswith("bearer "):
            presented = authorization[len("bearer ") :].strip()
    return hmac.compare_digest(presented.encode("utf-8"), TOKEN.encode("utf-8"))


@app.middleware("http")
async def guard(request: Request, call_next: Any) -> Any:
    """Refuse before the body is read.

    FastAPI parses the multipart form BEFORE a route's dependencies run,
    so a token check in the endpoint would already have buffered the
    upload. Here nothing has been read yet: an unauthenticated or
    oversized request costs one response and no memory.
    """
    if request.url.path == HEALTH_ROUTE:
        return await call_next(request)
    if not TOKEN and not ALLOW_ANONYMOUS:
        return JSONResponse({"detail": "server has no token configured"}, status_code=503)
    if not _authenticated(request.headers):
        return JSONResponse({"detail": "bad token"}, status_code=401)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        return JSONResponse({"detail": "audio too large"}, status_code=413)
    return await call_next(request)


@app.get(HEALTH_ROUTE)
async def health(request: Request) -> JSONResponse:
    """Liveness, and whether the caller's token would be accepted.

    Liveness is unauthenticated because the platform's probe has no
    token, and it answers before the weights are loaded: the model loads
    on the first diarization, which is what keeps a scaled-to-zero
    replica's wake-up honest. ``authenticated`` is what lets the worker
    find a wrong token at startup instead of silently producing
    speakerless transcripts for a week — and ``last_error`` (model
    paths, exception classes) is only for a caller that proved itself.
    """
    diarizer = getattr(app.state, "diarizer", None)
    authenticated = _authenticated(request.headers)
    body: dict[str, Any] = {
        "status": "ok",
        "model_id": MODEL_ID,
        "loaded": bool(diarizer and diarizer.ready),
        "authenticated": authenticated,
    }
    if authenticated:
        body["last_error"] = diarizer.last_error if diarizer else None
    return JSONResponse(body)


@app.post("/v1/audio/diarizations")
async def diarize(
    file: UploadFile,
    num_speakers: Annotated[int | None, Form()] = None,
    min_speakers: Annotated[int | None, Form()] = None,
    max_speakers: Annotated[int | None, Form()] = None,
    min_speaker_speech_ms: Annotated[int, Form()] = 0,
    min_speaker_share: Annotated[float, Form()] = 0.0,
    reassign_min_cosine: Annotated[float, Form()] = 0.5,
) -> Any:
    # `guard` checked the declared size; this is the honest byte count.
    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="audio too large")
    try:
        hints = DiarizationHints(
            num_speakers=num_speakers, min_speakers=min_speakers, max_speakers=max_speakers
        ).validated()
    except InvalidHintsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Bound the DECODED size before decoding (a near-silent FLAC expands enormously).
    try:
        seconds = audio_seconds(body)
    except Exception as exc:  # noqa: BLE001 — unreadable header, same answer
        raise HTTPException(
            status_code=415, detail=f"cannot read audio: {type(exc).__name__}"
        ) from exc
    if seconds > MAX_AUDIO_SECONDS:
        raise HTTPException(status_code=413, detail="recording too long")
    try:
        pcm = decode_audio(body)
    except Exception as exc:  # noqa: BLE001 — anything unreadable is the caller's problem
        raise HTTPException(
            status_code=415, detail=f"cannot decode audio: {type(exc).__name__}"
        ) from exc
    del body
    diarizer = app.state.diarizer
    await diarizer.ensure_loaded()
    # The floor is the caller's policy and applies to this request only.
    roster = RosterGuardConfig(
        min_speaker_speech_ms=max(0, min_speaker_speech_ms),
        min_speaker_share=max(0.0, min_speaker_share),
        reassign_min_cosine=reassign_min_cosine,
    )
    t0 = time.monotonic()
    # One pass at a time (MDX_DIAR_MAX_CONCURRENT): pipeline and GPU are shared.
    async with app.state.slots:
        result = await asyncio.to_thread(
            lambda: diarizer.diarize(pcm, 16_000, hints=hints, roster=roster)
        )
    elapsed = time.monotonic() - t0
    logger.info(
        "diar_server.diarized",
        extra={
            "audio_seconds": round(len(pcm) / 16_000, 1),
            "seconds": round(elapsed, 3),
            "speakers": len(result.speakers),
            "hint": hints.kind,
        },
    )
    return to_payload(result, model_id=MODEL_ID, seconds=elapsed)
