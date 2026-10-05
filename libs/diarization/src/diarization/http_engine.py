"""Remote engine: the same ``PyannoteDiarizer`` on a GPU endpoint (``deploy/diar-server``, ADR-0052).

Audio goes losslessly in the request body with no key, tenant id or filename; the reply carries labels, never
embeddings. Blocking like the other engines; scale-to-zero cold starts are covered by the timeout and retries.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import numpy as np

from .engine import DiarizationUnavailableError
from .offline import OfflineDiarization, OfflineDiarizationConfig
from .protocol import DiarizationHints
from .roster import RosterGuardConfig
from .wire import (
    DIARIZATIONS_PATH,
    HEALTH_PATH,
    SAMPLE_RATE_HZ,
    TOKEN_HEADER,
    encode_audio,
    from_payload,
    hint_fields,
)

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 5.0
# community-1 runs at ~0.15 × audio on a T4 (0.64–0.85 × on 4 CPU threads); a CPU endpoint needs a higher slope.
TIMEOUT_PER_AUDIO_SECOND = 0.5
MIN_TIMEOUT_S = 60.0
# 5xx/timeout retries with growing delays, continued until the declared cold start is covered (503 while waking).
MIN_RETRIES = 2
RETRY_BACKOFF_S = 2.0
MAX_RETRY_DELAY_S = 30.0
# Stripped despite global httpx instrumentation: the worker's spans carry job and tenant ids.
CORRELATION_HEADERS = ("traceparent", "tracestate", "baggage")


class HttpDiarizer:
    """Diarizer backed by ``POST {base_url}/v1/audio/diarizations``."""

    remote = True

    def __init__(
        self,
        *,
        backend: str,
        base_url: str,
        model_id: str,
        auth_token: str | None = None,
        server_token: str | None = None,
        cold_start_seconds: int = 0,
        timeout_seconds: float = 1800.0,
        seconds_per_audio_second: float = TIMEOUT_PER_AUDIO_SECOND,
        roster: RosterGuardConfig | None = None,
        offline_config: OfflineDiarizationConfig | None = None,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Any = None,
    ) -> None:
        self.engine = f"http:{backend}"
        self.engine_version = model_id or "unknown"
        self._backend = backend
        self._model_id = model_id
        self._cold_start_seconds = cold_start_seconds
        self._max_timeout_s = timeout_seconds
        self._per_audio_second = max(0.05, seconds_per_audio_second)
        self._roster = roster or RosterGuardConfig()
        self._config = offline_config or OfflineDiarizationConfig()
        self._ready = False
        self._last_error: str | None = None
        self._sleep = sleep or time.sleep
        headers = {}
        if auth_token:
            # Both: a managed gateway consumes `Authorization`; the bare container reads the bearer.
            headers["Authorization"] = f"Bearer {auth_token}"
            headers[TOKEN_HEADER] = auth_token
        if server_token:
            headers[TOKEN_HEADER] = server_token
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_S),
            event_hooks={"request": [_strip_correlation_headers]},
            transport=transport,
        )

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def ensure_loaded(self) -> None:
        """Health-check the endpoint (a scaled-to-zero one counts as ready); a bad URL/token surfaces at startup."""
        if self._ready:
            return
        import asyncio  # noqa: PLC0415 — only this method needs the loop

        try:
            response = await asyncio.to_thread(self._health)
        except httpx.HTTPError as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.error(
                "diarization.remote_unreachable",
                extra={"engine": self.engine, "error_class": type(exc).__name__},
            )
            raise DiarizationUnavailableError(
                f"{self.engine} is unreachable: {type(exc).__name__}"
            ) from exc
        if response.status_code in (401, 403):
            self._last_error = "auth"
            raise DiarizationUnavailableError(f"{self.engine} refused the token")
        # 503 while waking is not a failure: the diarize call waits out the cold start.
        if response.status_code >= 400 and response.status_code != 503:
            self._last_error = f"health_{response.status_code}"
            raise DiarizationUnavailableError(
                f"{self.engine} health check returned {response.status_code}"
            )
        # A wrong token would otherwise show up as speakerless transcripts job after job.
        if response.status_code < 400 and _rejects_us(response):
            self._last_error = "auth"
            raise DiarizationUnavailableError(
                f"{self.engine} does not accept this token (health says authenticated=false)"
            )
        self._ready = True
        self._last_error = None
        logger.info("diarization.remote_ready", extra={"engine": self.engine})

    def _health(self) -> httpx.Response:
        return self._client.get(HEALTH_PATH, timeout=httpx.Timeout(30.0, connect=CONNECT_TIMEOUT_S))

    def diarize(
        self, pcm: np.ndarray, sample_rate_hz: int, *, hints: DiarizationHints
    ) -> OfflineDiarization:
        if sample_rate_hz != SAMPLE_RATE_HZ:
            raise ValueError(f"{self.engine} requires {SAMPLE_RATE_HZ} Hz mono PCM")
        hints = hints.validated()
        filename, audio = encode_audio(pcm)
        audio_seconds = pcm.shape[0] / SAMPLE_RATE_HZ
        timeout = min(
            self._max_timeout_s,
            max(MIN_TIMEOUT_S, audio_seconds * TIMEOUT_PER_AUDIO_SECOND) + self._cold_start_seconds,
        )
        data = hint_fields(hints) | {
            # The worker's floor, applied where the embeddings are (roster.py).
            "min_speaker_speech_ms": str(self._roster.min_speaker_speech_ms),
            "min_speaker_share": str(self._roster.min_speaker_share),
            "reassign_min_cosine": str(self._roster.reassign_min_cosine),
        }
        payload = self._post(
            files={"file": (filename, audio, _media_type(filename))}, data=data, timeout=timeout
        )
        return from_payload(payload, hints=hints, config=self._config)

    def _post(self, *, files: dict[str, Any], data: dict[str, str], timeout: float) -> Any:
        last: Exception | None = None
        attempt = 0
        # The retry window covers the declared cold start (503 until up).
        waited = 0.0
        while True:
            try:
                response = self._client.post(
                    DIARIZATIONS_PATH,
                    files=files,
                    data=data,
                    timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT_S),
                )
            except httpx.HTTPError as exc:
                last = exc
            else:
                if response.status_code < 400:
                    return response.json()
                # 4xx is us; retrying cannot help.
                if response.status_code < 500:
                    self._ready = False
                    self._last_error = f"rejected_{response.status_code}"
                    raise DiarizationRequestError(
                        f"{self.engine} rejected the request: {response.status_code}"
                    )
                last = DiarizationRequestError(f"{self.engine} returned {response.status_code}")
            attempt += 1
            if attempt > MIN_RETRIES and waited >= self._cold_start_seconds:
                break
            delay = min(RETRY_BACKOFF_S * (2 ** (attempt - 1)), MAX_RETRY_DELAY_S)
            self._sleep(delay)
            waited += delay
        self._ready = False
        self._last_error = f"{type(last).__name__}: {last}"
        raise DiarizationUnavailableError(
            f"{self.engine} failed after {attempt} attempts: {type(last).__name__}"
        ) from last

    def close(self) -> None:
        """Release the connection pool (worker shutdown)."""
        self._client.close()


class DiarizationRequestError(DiarizationUnavailableError):
    """The endpoint refused this recording (4xx); a subclass so "unavailable" handlers cover it too."""


def _rejects_us(response: httpx.Response) -> bool:
    """Did a healthy endpoint say our token is not good enough?"""
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("authenticated") is False


def _strip_correlation_headers(request: httpx.Request) -> None:
    for name in CORRELATION_HEADERS:
        request.headers.pop(name, None)


def _media_type(filename: str) -> str:
    return "audio/flac" if filename.endswith(".flac") else "audio/wav"
