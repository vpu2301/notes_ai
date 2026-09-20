"""Remote engine: diarization on a GPU endpoint (Sprint 29 B-9, shape B).

Same :class:`~diarization.protocol.Diarizer` seam as the two in-process
engines, so the worker's word attribution, stats and re-run path are
unchanged — only the compute moves. The endpoint is our own image
(``deploy/diar-server``) running the very same ``PyannoteDiarizer``, so
labels do not depend on where the model ran.

Why this shape exists (ADR-0052): community-1 needs far more compute
than the legacy clusterer, and the staging worker is four CPU cores with
no GPU. Shape A (in-process) misses the turnaround budget there.

Rules this client keeps:

- **Audio is a request body, never a file on the endpoint.** It is sent
  losslessly (FLAC when ``soundfile`` is available, WAV otherwise), the
  server holds it in memory for the call, and no key, tenant id or
  filename goes with it.
- **The reply carries labels, never embeddings** — see ``wire.py``.
- **Blocking, like the other engines.** ``diarize()`` is called off the
  event loop by the worker, so it drives its own ``httpx`` client
  synchronously rather than pretending to be async.
- **A cold endpoint is normal.** Scale-to-zero means the first call of
  the day waits; the timeout budget is the recording's own length plus
  the backend's cold start, and 5xx/timeouts are retried twice.
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
# Wall-clock budget for one call: community-1 runs at roughly 0.15 ×
# audio on a T4 (0.64–0.85 × on four CPU threads — ADR-0052), so the
# default leaves triple headroom over a GPU pass. A CPU-hosted endpoint needs a
# slope above its own rate or every recording times out; that is what
# `seconds_per_audio_second` is for.
TIMEOUT_PER_AUDIO_SECOND = 0.5
MIN_TIMEOUT_S = 60.0
# Retries for 5xx and timeouts. A scale-to-zero endpoint answers 503
# while it wakes, so retrying must cover the cold start the backend
# declares, not a couple of seconds: the delays grow 2, 4, 8 … and the
# loop keeps going until that budget is spent.
MIN_RETRIES = 2
RETRY_BACKOFF_S = 2.0
MAX_RETRY_DELAY_S = 30.0
# Tracing headers identify the worker's trace, and its spans carry job
# and tenant ids. The endpoint gets audio and nothing that ties it to a
# person, so they are stripped even though httpx is instrumented
# globally (observability.tracing).
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
            # Both: a managed endpoint's gateway consumes `Authorization`
            # for its own check, so the server reads our token from its
            # own header and falls back to the bearer for a bare
            # container (deploy/diar-server).
            headers["Authorization"] = f"Bearer {auth_token}"
            headers[TOKEN_HEADER] = auth_token
        if server_token:
            headers[TOKEN_HEADER] = server_token
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_S),
            event_hooks={"request": [_strip_correlation_headers]},
            # A caller may hand in the transport (tests) and still get the
            # headers and hooks this class is responsible for.
            transport=transport,
        )

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def ensure_loaded(self) -> None:
        """Health-check the endpoint; a scaled-to-zero one counts as ready.

        The endpoint loads its own weights, so there is nothing to load
        here. What this checks is that the worker can reach it at all —
        a wrong URL or a revoked token is a configuration error and must
        surface before a job is attributed to a broken backend, not as a
        mysterious failure per recording.
        """
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
        # 503 while a scaled-to-zero endpoint wakes up is not a failure:
        # the diarize call itself waits out the cold start.
        if response.status_code >= 400 and response.status_code != 503:
            self._last_error = f"health_{response.status_code}"
            raise DiarizationUnavailableError(
                f"{self.engine} health check returned {response.status_code}"
            )
        # A wrong token would otherwise show up as speakerless
        # transcripts, job after job, with nobody paged: the endpoint
        # answers whether it would accept us, and a `false` here is a
        # configuration error that belongs at startup.
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
            # The floor is the worker's policy; it is applied where the
            # embeddings are so a dissolved speaker can still be moved to
            # the voice it belongs to (roster.py).
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
        # A scaled-to-zero endpoint answers 503 until it is up, so the
        # retry window covers the cold start the backend declares —
        # otherwise the first job after every idle spell loses its
        # speakers to a wake-up we knew was coming.
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
                # 4xx is us (a hint the server rejects, a revoked token);
                # retrying cannot help and would multiply the cost.
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
    """The endpoint refused this recording (4xx) — retrying will not help.

    A subclass, so every caller that already handles "the diarizer is not
    available" handles this too; only code that wants to tell a refusal
    from an outage needs to know the difference.
    """


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
