"""asr-server — Parakeet-TDT-0.6B-v3 behind an OpenAI-style transcription
route (Sprint TQ4 T1, the bake-off's arm C).

The worker talks to it like any ``asr_http`` backend (ADR-0046):
``POST /v1/audio/transcriptions`` with ``file``, ``language``,
``response_format=verbose_json`` and ``timestamp_granularities[]=word`` →
``{text, segments[], words[]}``. The worker sends speech runs grouped by
language (TQ2), so a request is at most a few minutes; long files are
handled anyway (local attention, ``parakeet_engines.py``).

What it does NOT do, by design (same contract as ``deploy/diar-server``):

* **No storage.** The audio lives in the request's memory only.
* **No identifiers.** No tenant, job, user or filename reaches it.
* **No network.** Weights are baked and digest-checked at build time;
  ``HF_HUB_OFFLINE=1`` and the other hub switches are pinned before any
  model library is imported. NeMo has no usage telemetry to turn off
  (checked for 3.0.0: no analytics client in the package); the pins stop
  the hub, NGC and Transformers lookups a model library can make.

Logs carry timings and counts only. Authentication is a bearer token
(``MDX_ASR_SERVER_TOKEN``, or the ``x-mdx-asr-token`` header behind a
gateway); with none set the server refuses to start unless
``MDX_ASR_SERVER_ALLOW_ANONYMOUS=1`` (a laptop).

    MDX_ASR_RUNTIME=nemo uvicorn app:app --host 0.0.0.0 --port 8082   # endpoint
    MDX_ASR_RUNTIME=onnx MDX_ASR_SERVER_ALLOW_ANONYMOUS=1 uvicorn app:app --port 8082   # Mac
"""

from __future__ import annotations

import asyncio
import hmac
import io
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import numpy as np
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.formparsers import MultiPartParser

PIN_ENVIRON = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "WANDB_MODE": "disabled",
    "NEMO_DISABLE_DOWNLOADS": "1",
}
for _k, _v in PIN_ENVIRON.items():  # before any model library is imported
    os.environ.setdefault(_k, _v)

from parakeet_engines import Engine, build  # noqa: E402
from parakeet_format import verbose_json  # noqa: E402

logger = logging.getLogger("asr_server")

RUNTIME = os.environ.get("MDX_ASR_RUNTIME", "nemo")
TOKEN = os.environ.get("MDX_ASR_SERVER_TOKEN", "")
ALLOW_ANONYMOUS = os.environ.get("MDX_ASR_SERVER_ALLOW_ANONYMOUS", "") == "1"
TOKEN_HEADER = "x-mdx-asr-token"
MAX_CONCURRENT = max(1, int(os.environ.get("MDX_ASR_MAX_CONCURRENT", "1")))
MAX_AUDIO_SECONDS = float(os.environ.get("MDX_ASR_MAX_AUDIO_SECONDS", "7500"))
MAX_UPLOAD_BYTES = int(os.environ.get("MDX_ASR_MAX_UPLOAD_BYTES", str(300 * 1024 * 1024)))
# Never spool the caller's audio to a temp file (see diar-server).
MultiPartParser.spool_max_size = MAX_UPLOAD_BYTES + (1 << 20)
HEALTH_ROUTE = "/health"


def decode(body: bytes) -> np.ndarray:
    """Any container ffmpeg / libsndfile reads → mono 16 kHz float32."""
    import soundfile as sf

    data, rate = sf.read(io.BytesIO(body), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if rate != 16_000:
        import soxr

        mono = soxr.resample(mono, rate, 16_000)
    return np.ascontiguousarray(mono, dtype=np.float32)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not TOKEN and not ALLOW_ANONYMOUS:
        raise RuntimeError(
            "MDX_ASR_SERVER_TOKEN is empty; set it, or MDX_ASR_SERVER_ALLOW_ANONYMOUS=1 for a laptop"
        )
    app.state.slots = asyncio.Semaphore(MAX_CONCURRENT)
    app.state.engine = build(RUNTIME)
    app.state.loaded = False
    app.state.load_lock = asyncio.Lock()
    yield


app = FastAPI(title="asr-server", lifespan=lifespan, docs_url=None, redoc_url=None)


def _authenticated(headers: Any) -> bool:
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
    """Refuse before the body is read (FastAPI parses forms first)."""
    if request.url.path == HEALTH_ROUTE:
        return await call_next(request)
    if not _authenticated(request.headers):
        return JSONResponse({"detail": "bad token"}, status_code=401)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        return JSONResponse({"detail": "audio too large"}, status_code=413)
    return await call_next(request)


@app.get(HEALTH_ROUTE)
async def health() -> JSONResponse:
    engine = getattr(app.state, "engine", None)
    return JSONResponse(
        {
            "status": "ok",
            "model_id": engine.model_id if engine else None,
            "runtime": RUNTIME,
            "loaded": bool(getattr(app.state, "loaded", False)),
        }
    )


async def _ensure_loaded(engine: Engine) -> None:
    if app.state.loaded:
        return
    async with app.state.load_lock:
        if not app.state.loaded:
            await asyncio.to_thread(engine.load)
            app.state.loaded = True


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile,
    language: Annotated[str | None, Form()] = None,
    response_format: Annotated[str, Form()] = "verbose_json",
    model: Annotated[str | None, Form()] = None,
    prompt: Annotated[str | None, Form()] = None,
) -> Any:
    # ``prompt``: accepted and ignored — Parakeet has no prompt biasing
    # (TQ4 fact 4); the worker's glossary and the TQ3 unifier carry names.
    del model, prompt
    if response_format != "verbose_json":
        raise HTTPException(status_code=400, detail="only verbose_json is served")
    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="audio too large")
    try:
        pcm = decode(body)
    except Exception as exc:  # noqa: BLE001 — anything unreadable is the caller's problem
        raise HTTPException(
            status_code=415, detail=f"cannot decode audio: {type(exc).__name__}"
        ) from exc
    del body
    duration = len(pcm) / 16_000
    if duration > MAX_AUDIO_SECONDS:
        raise HTTPException(status_code=413, detail="recording too long")
    engine: Engine = app.state.engine
    await _ensure_loaded(engine)
    t0 = time.monotonic()
    async with app.state.slots:
        words = await asyncio.to_thread(engine.transcribe, pcm) if pcm.size else []
    elapsed = time.monotonic() - t0
    logger.info(
        "asr_server.transcribed",
        extra={
            "audio_seconds": round(duration, 1),
            "seconds": round(elapsed, 3),
            "words": len(words),
        },
    )
    return verbose_json(words, duration=duration, language=language)
