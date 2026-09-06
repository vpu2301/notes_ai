"""``ASRProvider`` over ``POST /v1/audio/transcriptions``-compatible servers.

Works against whisper.cpp's server (``--inference-path /v1/audio/transcriptions``),
Speaches / faster-whisper-server, vLLM's Whisper route and a Hugging Face
Inference Endpoint deployed behind an OpenAI-compatible handler. Requests
``response_format=verbose_json`` with word granularity and accepts both
response shapes in the wild: words nested per segment (whisper.cpp) and a
top-level ``words[]`` (OpenAI / Speaches).

Word timings are a contract (ADR-0037): ``warm_up`` sends the bundled probe
clip and refuses the backend if the reply carries no ``words``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import numpy as np

from asr_models import (
    AUTO_LANGUAGE,
    Segment,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)

from .audio import SAMPLE_RATE, pcm_to_wav_bytes, probe_clip_path, wav_file_to_pcm
from .errors import ErrorKind, ProviderError, TranscriptionCancelledError, register_secret
from .protocols import ShouldCancel
from .usage import UsageRecord, emit

logger = logging.getLogger("models.asr_http")

CONNECT_TIMEOUT_S = 5.0
CANCEL_POLL_S = 1.0
WARMING_POLL_S = 30.0
TRANSCRIPTIONS_PATH = "/v1/audio/transcriptions"
_LANGUAGE_NAMES = {
    "english": "en",
    "german": "de",
    "ukrainian": "uk",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "polish": "pl",
    "dutch": "nl",
    "portuguese": "pt",
    "russian": "ru",
}


class HTTPASRProvider:
    def __init__(
        self,
        *,
        backend: str,
        base_url: str,
        model_id: str,
        auth_token: str | None = None,
        timeout_s: float = 600.0,
        cold_start_seconds: int = 0,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.backend = backend
        self._sleep: Callable[[float], Awaitable[None]] = sleep or asyncio.sleep
        self._model = model_id
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._cold_start_seconds = cold_start_seconds
        self._loaded = False
        self._warmup_seconds = 0.0
        register_secret(auth_token)
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S),
        )
        self._owns_client = client is None

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def warmup_seconds(self) -> float:
        return self._warmup_seconds

    async def warm_up(self) -> None:
        """Probe with the bundled clip; reject servers without word timestamps."""
        t0 = time.monotonic()
        pcm = wav_file_to_pcm(probe_clip_path())
        out = await self._transcribe_once(pcm, language="en", prompt=None)
        if not any(seg.words for seg in out.segments):
            raise ProviderError(
                ErrorKind.UNKNOWN,
                "asr_backend_without_word_timestamps: probe reply carried no words[] (ADR-0037 needs them)",
                backend=self.backend,
            )
        self._warmup_seconds = time.monotonic() - t0
        self._loaded = True
        logger.info(
            "models.asr_probe_ok",
            extra={
                "backend": self.backend,
                "model_id": self._model,
                "warmup_seconds": round(self._warmup_seconds, 3),
            },
        )

    async def transcribe(
        self,
        audio_pcm: np.ndarray,
        *,
        language: str,
        prompt: str | None,
        should_cancel: ShouldCancel | None = None,
    ) -> TranscriptionOutput:
        if not self._loaded:
            raise RuntimeError("HTTPASRProvider.warm_up() must succeed before transcribe()")
        started = time.monotonic()
        audio_seconds = float(len(audio_pcm)) / SAMPLE_RATE
        task = asyncio.create_task(
            self._transcribe_with_warming(audio_pcm, language=language, prompt=prompt)
        )
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=CANCEL_POLL_S)
                if done:
                    break
                if should_cancel is not None and await should_cancel():
                    task.cancel()
                    raise TranscriptionCancelledError("cancel requested during HTTP transcription")
            output = task.result()
        except ProviderError as exc:
            emit(
                UsageRecord(
                    backend=self.backend,
                    model_id=self._model,
                    operation="asr.transcribe",
                    ok=False,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    audio_seconds=audio_seconds,
                    error_kind=str(exc.kind),
                )
            )
            raise
        emit(
            UsageRecord(
                backend=self.backend,
                model_id=self._model,
                operation="asr.transcribe",
                ok=True,
                latency_ms=int((time.monotonic() - started) * 1000),
                audio_seconds=audio_seconds,
            )
        )
        return output

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ── request / response ──────────────────────────────────────────────
    async def _transcribe_with_warming(
        self, pcm: np.ndarray, *, language: str, prompt: str | None
    ) -> TranscriptionOutput:
        """Absorb a scale-to-zero wake-up: retry `warming` within cold_start_seconds.

        asr-worker consumes Redis Streams (no delayed re-queue), so the wait
        happens here; the job's attempt is not consumed. Anything else
        surfaces immediately for the job policy to classify.
        """
        waited = 0.0
        while True:
            try:
                return await self._transcribe_once(pcm, language=language, prompt=prompt)
            except ProviderError as exc:
                if exc.kind is not ErrorKind.WARMING or waited >= self._cold_start_seconds:
                    raise
                delay = max(
                    0.1, min(exc.retry_after_s or WARMING_POLL_S, self._cold_start_seconds - waited)
                )
                logger.info(
                    "models.asr_warming",
                    extra={"backend": self.backend, "waited_s": round(waited), "delay_s": delay},
                )
                await self._sleep(delay)
                waited += delay

    async def _transcribe_once(
        self, pcm: np.ndarray, *, language: str, prompt: str | None
    ) -> TranscriptionOutput:
        t0 = time.monotonic()
        data: dict[str, Any] = {
            "model": self._model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
        if language and language != AUTO_LANGUAGE:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt
        files = {"file": ("audio.wav", pcm_to_wav_bytes(pcm), "audio/wav")}
        try:
            resp = await self._client.post(TRANSCRIPTIONS_PATH, data=data, files=files)
        except httpx.ConnectTimeout as exc:
            raise ProviderError(ErrorKind.TIMEOUT, "connect timeout", backend=self.backend) from exc
        except httpx.ConnectError as exc:
            raise ProviderError(
                ErrorKind.UNAVAILABLE, "connection refused", backend=self.backend
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ErrorKind.TIMEOUT,
                f"read timeout after {self._timeout_s:.0f}s",
                backend=self.backend,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                ErrorKind.UNAVAILABLE, type(exc).__name__, backend=self.backend
            ) from exc
        if resp.status_code >= 400:
            raise self._map_status(resp)
        try:
            body = resp.json()
        except ValueError as exc:
            raise ProviderError(
                ErrorKind.UNAVAILABLE, "non-JSON transcription response", backend=self.backend
            ) from exc
        if not isinstance(body, dict):
            raise ProviderError(
                ErrorKind.UNAVAILABLE,
                "unexpected transcription response shape",
                backend=self.backend,
            )
        infer_seconds = time.monotonic() - t0
        return _to_output(
            body,
            model=self._model,
            requested_language=language,
            audio_seconds=len(pcm) / SAMPLE_RATE,
            infer_seconds=infer_seconds,
        )

    def _map_status(self, resp: httpx.Response) -> ProviderError:
        status = resp.status_code
        text = resp.text[:200]
        if status in (401, 403):
            return ProviderError(
                ErrorKind.AUTH, f"HTTP {status}", backend=self.backend, status=status
            )
        if status == 429:
            return ProviderError(
                ErrorKind.RATE_LIMITED, f"HTTP 429 {text}", backend=self.backend, status=status
            )
        if status == 413:
            return ProviderError(
                ErrorKind.CONTEXT_EXCEEDED,
                "HTTP 413 audio too large for this endpoint",
                backend=self.backend,
                status=status,
            )
        if status in (408, 504):
            return ProviderError(
                ErrorKind.TIMEOUT, f"HTTP {status}", backend=self.backend, status=status
            )
        if status == 503:
            kind = ErrorKind.WARMING if self._cold_start_seconds > 0 else ErrorKind.UNAVAILABLE
            retry_after = resp.headers.get("retry-after")
            return ProviderError(
                kind,
                f"HTTP 503 {text}",
                backend=self.backend,
                status=status,
                retry_after_s=float(retry_after)
                if retry_after and retry_after.replace(".", "", 1).isdigit()
                else None,
            )
        if status >= 500:
            return ProviderError(
                ErrorKind.UNAVAILABLE, f"HTTP {status} {text}", backend=self.backend, status=status
            )
        return ProviderError(
            ErrorKind.UNKNOWN, f"HTTP {status} {text}", backend=self.backend, status=status
        )


def _ms(value: Any) -> int:
    try:
        return max(0, int(round(float(value) * 1000)))
    except (TypeError, ValueError):
        return 0


_PUNCT_ONLY = re.compile(r"^[\W_]+$")


def _word(raw: dict[str, Any]) -> WordTiming | None:
    text = str(raw.get("word") or raw.get("text") or "").strip()
    if not text:
        return None
    prob = raw.get("probability", raw.get("confidence", 1.0))
    try:
        p = min(1.0, max(0.0, float(prob)))
    except (TypeError, ValueError):
        p = 1.0
    start, end = _ms(raw.get("start")), _ms(raw.get("end"))
    return WordTiming(text=text, start_ms=start, end_ms=max(start, end), probability=p)


def _merge_punctuation(words: list[WordTiming]) -> list[WordTiming]:
    """whisper.cpp emits "," / "." as their own tokens; faster-whisper glues
    them to the preceding word ("three,"). Match the in-process shape so
    downstream turn/paragraph logic sees one convention."""
    merged: list[WordTiming] = []
    for w in words:
        if merged and _PUNCT_ONLY.match(w.text):
            prev = merged[-1]
            merged[-1] = WordTiming(
                text=prev.text + w.text,
                start_ms=prev.start_ms,
                end_ms=max(prev.end_ms, w.end_ms),
                probability=prev.probability,
            )
        else:
            merged.append(w)
    return merged


def _words(raw_list: Any) -> list[WordTiming]:
    if not isinstance(raw_list, list):
        return []
    return _merge_punctuation([w for w in (_word(x) for x in raw_list if isinstance(x, dict)) if w])


def _to_output(
    body: dict[str, Any],
    *,
    model: str,
    requested_language: str,
    audio_seconds: float,
    infer_seconds: float,
) -> TranscriptionOutput:
    raw_segments = body.get("segments") or []
    top_words = _words(body.get("words"))
    segments: list[Segment] = []
    if not raw_segments and (body.get("text") or top_words):
        # Server returned text + words but no segments: one segment.
        text = str(body.get("text") or " ".join(w.text for w in top_words)).strip()
        start = top_words[0].start_ms if top_words else 0
        end = top_words[-1].end_ms if top_words else _ms(body.get("duration", audio_seconds))
        raw_segments = [{"text": text, "start": start / 1000, "end": end / 1000}]
    for raw in raw_segments:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        start, end = _ms(raw.get("start")), _ms(raw.get("end"))
        end = max(start, end)
        words = _words(raw.get("words"))
        if not words and top_words:
            words = [w for w in top_words if w.start_ms >= start and w.start_ms < end] or [
                w for w in top_words if w.end_ms > start and w.start_ms < end
            ]
        avg = sum(w.probability for w in words) / len(words) if words else 0.5
        segments.append(
            Segment(text=text, start_ms=start, end_ms=end, words=words, avg_confidence=avg)
        )
    language = _normalise_language(
        body.get("language") or body.get("detected_language"), requested_language
    )
    detected = requested_language == AUTO_LANGUAGE
    prob = body.get("language_probability", body.get("detected_language_probability"))
    metadata = TranscriptionMetadata(
        model=model,
        vad_seconds_speech=float(body.get("duration") or audio_seconds),
        infer_seconds=infer_seconds,
        beam_size=1,
    )
    return TranscriptionOutput(
        language=language,
        language_detected=detected,
        language_probability=float(prob) if isinstance(prob, int | float) else None,
        segments=segments,
        metadata=metadata,
    )


def _normalise_language(value: Any, requested: str) -> str:
    if isinstance(value, str) and value:
        v = value.strip().lower()
        if v in _LANGUAGE_NAMES:
            return _LANGUAGE_NAMES[v]
        if 2 <= len(v) <= 3 and v.isalpha():
            return v
    if requested and requested != AUTO_LANGUAGE:
        return requested
    return "en"
