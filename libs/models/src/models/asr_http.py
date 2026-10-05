"""``ASRProvider`` over ``POST /v1/audio/transcriptions``-compatible servers (whisper.cpp, Speaches, vLLM, HF).

Accepts words nested per segment or top-level ``words[]``; ``warm_up`` refuses a backend without word timings (ADR-0037).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx
import numpy as np

from asr_models import (
    AUTO_LANGUAGE,
    BackendError,
    Diagnostics,
    Segment,
    SegmentDiagnostics,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)

from .audio import SAMPLE_RATE, pcm_to_wav_bytes, probe_clip_path, wav_file_to_pcm
from .errors import ErrorKind, ProviderError, TranscriptionCancelledError, register_secret
from .protocols import ShouldCancel, SpeechRun
from .run_groups import plan_groups, remap
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


SERVER_TOKEN_HEADER = "x-mdx-asr-token"


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
        server_token: str | None = None,
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
        register_secret(server_token)
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
        # Own header: behind a managed endpoint the gateway consumes `Authorization`.
        if server_token:
            headers[SERVER_TOKEN_HEADER] = server_token
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
        second_pass: bool = False,
    ) -> TranscriptionOutput:
        # No beam/conditioning switch on this API; "no prompt" is the part of second_pass it can honour.
        del second_pass
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

    async def transcribe_runs(
        self,
        audio_pcm: np.ndarray,
        runs: Sequence[SpeechRun],
        *,
        language: str,
        prompt: str | None,
        should_cancel: ShouldCancel | None = None,
        group_seconds: float = 300.0,
    ) -> TranscriptionOutput:
        """One request per language group (``run_groups``). A failed group becomes a ``backend_errors`` coverage
        gap, unless nothing was decoded yet and the error is retryable: then the job is retried whole."""
        started = time.monotonic()
        groups = plan_groups(runs, group_seconds)
        segments: list[Segment] = []
        seg_diags: list[SegmentDiagnostics] = []
        errors: list[BackendError] = []
        detected: str | None = None
        probability: float | None = None
        decoded_any = False
        for group in groups:
            if should_cancel is not None and await should_cancel():
                raise TranscriptionCancelledError("cancel requested between run groups")
            try:
                out = await self.transcribe(
                    group.audio(audio_pcm),
                    language=group.language,
                    prompt=prompt,
                    should_cancel=should_cancel,
                )
            except ProviderError as exc:
                if exc.retryable and not decoded_any:
                    raise
                logger.warning(
                    "models.asr_group_failed",
                    extra={
                        "backend": self.backend,
                        "kind": str(exc.kind),
                        "start_ms": group.start_ms,
                        "runs": len(group.runs),
                    },
                )
                errors.extend(
                    BackendError(
                        start_ms=r.start_ms,
                        end_ms=r.end_ms,
                        kind=str(exc.kind)[:32],
                        language=r.language if r.language != AUTO_LANGUAGE else None,
                    )
                    for r in group.runs
                )
                continue
            decoded_any = True
            if group.language == AUTO_LANGUAGE and detected is None:
                detected, probability = out.language, out.language_probability
            recording = language if language != AUTO_LANGUAGE else (detected or out.language)
            label = None if group.language in (recording, AUTO_LANGUAGE) else group.language
            mapped = remap(out, group, label=label)
            segments.extend(mapped.segments)
            seg_diags.extend(mapped.diagnostics.segments)
        if groups and not decoded_any:
            raise ProviderError(
                ErrorKind.UNAVAILABLE,
                f"every run group failed ({len(groups)})",
                backend=self.backend,
            )
        segments.sort(key=lambda seg: seg.start_ms)
        seg_diags.sort(key=lambda d: d.start_ms)
        final_language = language if language != AUTO_LANGUAGE else (detected or "en")
        return TranscriptionOutput(
            language=final_language,
            language_detected=language == AUTO_LANGUAGE,
            language_probability=probability,
            segments=segments,
            metadata=TranscriptionMetadata(
                model=self._model,
                vad_seconds_speech=sum(r.end_ms - r.start_ms for r in runs) / 1000,
                infer_seconds=time.monotonic() - started,
                beam_size=1,
            ),
            diagnostics=Diagnostics(segments=seg_diags, backend_errors=errors),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _transcribe_with_warming(
        self, pcm: np.ndarray, *, language: str, prompt: str | None
    ) -> TranscriptionOutput:
        """Retry `warming` within cold_start_seconds (Redis Streams has no delayed re-queue); anything else surfaces."""
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
    """whisper.cpp emits punctuation as its own tokens; glue it to the preceding word like faster-whisper does."""
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


def _raw_text(raw: dict[str, Any]) -> str:
    return str(raw.get("word") or raw.get("text") or "")


def _merge_subwords(raw_list: list[dict[str, Any]]) -> list[WordTiming]:
    """whisper.cpp ``words`` are decoder tokens (a leading space begins a word); join them: first start, last end,
    lowest probability."""
    merged: list[WordTiming] = []
    for raw in raw_list:
        w = _word(raw)
        if w is None:
            continue
        if merged and not _raw_text(raw)[:1].isspace():
            prev = merged[-1]
            merged[-1] = WordTiming(
                text=prev.text + w.text,
                start_ms=prev.start_ms,
                end_ms=max(prev.end_ms, w.end_ms),
                probability=min(prev.probability, w.probability),
            )
        else:
            merged.append(w)
    return merged


def _words(raw_list: Any) -> list[WordTiming]:
    if not isinstance(raw_list, list):
        return []
    items = [x for x in raw_list if isinstance(x, dict)]
    # Leading spaces mark whisper.cpp's token convention; OpenAI / Speaches words carry none.
    if any(_raw_text(x)[:1].isspace() for x in items):
        return _merge_punctuation(_merge_subwords(items))
    return _merge_punctuation([w for w in (_word(x) for x in items) if w])


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
    seg_diagnostics: list[SegmentDiagnostics] = []
    if not raw_segments and (body.get("text") or top_words):
        text = str(body.get("text") or " ".join(w.text for w in top_words)).strip()
        start = top_words[0].start_ms if top_words else 0
        end = top_words[-1].end_ms if top_words else _ms(body.get("duration", audio_seconds))
        raw_segments = [{"text": text, "start": start / 1000, "end": end / 1000}]
    for raw in raw_segments:
        if not isinstance(raw, dict):
            continue
        start, end = _ms(raw.get("start")), _ms(raw.get("end"))
        end = max(start, end)
        # Recorded for every returned segment, empty ones included.
        seg_diagnostics.append(
            SegmentDiagnostics(
                start_ms=start,
                end_ms=end,
                no_speech_prob=_float_or_none(raw.get("no_speech_prob")),
                avg_logprob=_float_or_none(raw.get("avg_logprob")),
                compression_ratio=_float_or_none(raw.get("compression_ratio")),
            )
        )
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
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
    # A server that names no language (Parakeet) has not detected one; "en" is only a fallback.
    detected = requested_language == AUTO_LANGUAGE and bool(
        body.get("language") or body.get("detected_language")
    )
    prob = body.get("language_probability", body.get("detected_language_probability"))
    metadata = TranscriptionMetadata(
        model=model,
        vad_seconds_speech=float(body.get("duration") or audio_seconds),
        infer_seconds=infer_seconds,
        beam_size=1,
    )
    seg_diagnostics = [d.model_copy(update={"language": language}) for d in seg_diagnostics]
    # Words with no probability read as 1.0 above; the low-confidence gate must know.
    raw_words = list(body.get("words") or []) + [
        w for seg in raw_segments if isinstance(seg, dict) for w in (seg.get("words") or [])
    ]
    unscored = sum(
        1
        for w in raw_words
        if isinstance(w, dict) and w.get("probability") is None and w.get("confidence") is None
    )
    return TranscriptionOutput(
        language=language,
        language_detected=detected,
        language_probability=float(prob) if isinstance(prob, int | float) else None,
        segments=segments,
        metadata=metadata,
        diagnostics=Diagnostics(
            segments=seg_diagnostics,
            gate_unavailable={"word_probability": unscored} if unscored else {},
        ),
    )


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    f = float(value)
    return f if f == f else None


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
