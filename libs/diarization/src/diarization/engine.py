"""Legacy per-process engine (ADR-0034): one shared ECAPA embedder + Silero segmenter pair, loaded lazily under a lock.

Load failure raises :class:`DiarizationUnavailableError`: fail-loud, never a silent stub.
"""

from __future__ import annotations

import asyncio
import logging
import time

import numpy as np

from .embedder import EcapaEmbedder
from .integrity import verify_model_dir
from .offline import (
    ENGINE_ID,
    ENGINE_VERSION,
    OfflineDiarization,
    OfflineDiarizationConfig,
    diarize_offline,
)
from .protocol import DiarizationHints
from .roster import RosterGuardConfig
from .vad import SileroSegmenter

logger = logging.getLogger(__name__)


class DiarizationUnavailableError(Exception):
    """Diarization was requested but the diarizer cannot load."""


class LegacyEcapaDiarizer:
    engine = ENGINE_ID
    engine_version = ENGINE_VERSION
    remote = False

    def __init__(
        self,
        *,
        model_dir: str,
        device: str = "cpu",
        enabled: bool = True,
        pins: dict[str, str] | None = None,
        model_repo: str = "",
        model_revision: str = "",
        disabled_reason: str = "diarization disabled by configuration",
        offline_config: OfflineDiarizationConfig | None = None,
        roster: RosterGuardConfig | None = None,
    ) -> None:
        self._offline_config = offline_config
        self._roster = roster
        self._model_dir = model_dir
        self._device = device
        self._enabled = enabled
        self._pins = pins or {}
        self._model_repo = model_repo
        self._model_revision = model_revision
        self._disabled_reason = disabled_reason
        self._embedder: EcapaEmbedder | None = None
        self._segmenter: SileroSegmenter | None = None
        self._lock = asyncio.Lock()
        self._last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def loaded(self) -> bool:
        return self._embedder is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def model_dir(self) -> str:
        return self._model_dir

    @property
    def device(self) -> str:
        return self._device

    @property
    def ready(self) -> bool:
        """True iff this process can diarize RIGHT NOW (readiness gates on it; a cold load blows the latency budget)."""
        return self._enabled and self.loaded

    @property
    def embedder(self) -> EcapaEmbedder:
        """The loaded embedder; raises if ``ensure_loaded()`` has not run."""
        if self._embedder is None:
            raise DiarizationUnavailableError("diarizer not loaded; call ensure_loaded() first")
        return self._embedder

    @property
    def segmenter(self) -> SileroSegmenter:
        """The loaded segmenter; raises if ``ensure_loaded()`` has not run."""
        if self._segmenter is None:
            raise DiarizationUnavailableError("diarizer not loaded; call ensure_loaded() first")
        return self._segmenter

    async def ensure_loaded(self) -> None:
        if not self._enabled:
            raise DiarizationUnavailableError(self._disabled_reason)
        if self.loaded:
            return
        async with self._lock:
            if self.loaded:
                return
            embedder = EcapaEmbedder(model_dir=self._model_dir, device=self._device)
            segmenter = SileroSegmenter()
            try:
                # Re-assert the build-time digests before the weights are loaded (docs/models/PINS.md).
                await asyncio.to_thread(
                    verify_model_dir,
                    self._model_dir,
                    pins=self._pins,
                    repo=self._model_repo,
                    revision=self._model_revision,
                )
                await asyncio.to_thread(embedder.warm_up)
                await asyncio.to_thread(segmenter.speech_regions, np.zeros(1600, dtype=np.float32))
            except Exception as exc:  # torch/model errors are varied; fail loud, typed
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "diarization.load_failed",
                    extra={"model_dir": self._model_dir, "error_class": type(exc).__name__},
                )
                raise DiarizationUnavailableError(
                    f"diarizer failed to load from {self._model_dir}: {type(exc).__name__}"
                ) from exc
            self._embedder = embedder
            self._segmenter = segmenter
            self._last_error = None
            logger.info(
                "diarization.loaded",
                extra={"model_dir": self._model_dir, "device": self._device},
            )

    def diarize(
        self, pcm: np.ndarray, sample_rate_hz: int, *, hints: DiarizationHints
    ) -> OfflineDiarization:
        """Whole-recording diarization (today's code path, plus hints/guard)."""
        return diarize_offline(
            pcm,
            sample_rate_hz,
            embedder=self.embedder,
            segmenter=self.segmenter,
            config=self._offline_config,
            hints=hints,
            roster=self._roster,
        )

    async def warm_up(self) -> bool:
        """Startup warmup that never blocks service start; a failure is recorded in ``last_error``."""
        if not self._enabled:
            logger.info("diarization.warmup_skipped", extra={"reason": "disabled"})
            return False
        t0 = time.monotonic()
        try:
            await self.ensure_loaded()
        except DiarizationUnavailableError as exc:
            logger.error(
                "diarization.warmup_failed",
                extra={
                    "model_dir": self._model_dir,
                    "error": str(exc),
                    "impact": "process serves non-diarized work only; diarization refused",
                },
            )
            return False
        logger.info(
            "diarization.warmed",
            extra={
                "model_dir": self._model_dir,
                "device": self._device,
                "warmup_ms": round((time.monotonic() - t0) * 1000, 1),
            },
        )
        return True


# dictation-service imports it under this name.
DiarizationEngine = LegacyEcapaDiarizer
