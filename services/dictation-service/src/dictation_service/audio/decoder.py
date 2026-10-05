"""Per-session Opus decoder (stateful codec: never share across sessions). ``opuslib`` is imported lazily."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# Wire constants for the dictation client.
SAMPLE_RATE_HZ: int = 16_000
CHANNELS: int = 1
FRAME_MS: int = 20
SAMPLES_PER_FRAME: int = SAMPLE_RATE_HZ * FRAME_MS // 1000  # 320
# A 20-ms Opus frame is typically 60-90 bytes; 1500 is the absolute upper bound.


class OpusDecodeError(Exception):
    def __init__(self, detail: str, *, fatal: bool = False) -> None:
        super().__init__(detail)
        self.fatal = fatal


@dataclass
class _DecodeStats:
    frames_ok: int = 0
    frames_failed: int = 0
    consecutive_failures: int = 0


class OpusDecoder:
    """Stateful Opus → float32 PCM; five consecutive failures raise ``OpusDecodeError(fatal=True)``."""

    _MAX_CONSECUTIVE_FAILURES: int = 5

    def __init__(self) -> None:
        self._decoder: object | None = None
        self._stats = _DecodeStats()
        self._load()

    def _load(self) -> None:
        try:
            import opuslib

            self._decoder = opuslib.Decoder(SAMPLE_RATE_HZ, CHANNELS)
        except Exception as exc:  # noqa: BLE001
            # No libopus (dev hosts): stub decoder returns silence.
            logger.warning(
                "opus.unavailable_fallback",
                extra={"error": str(exc), "error_class": type(exc).__name__},
            )
            self._decoder = None

    def decode(self, opus_bytes: bytes) -> np.ndarray:
        """Decode one 20-ms Opus packet → 320 float32 samples."""
        if self._decoder is None:
            # Stub path — return silence so framing tests still progress.
            self._stats.frames_ok += 1
            self._stats.consecutive_failures = 0
            return np.zeros(SAMPLES_PER_FRAME, dtype=np.float32)

        try:
            # opuslib returns bytes of int16 little-endian samples.
            pcm_bytes = self._decoder.decode(opus_bytes, SAMPLES_PER_FRAME, decode_fec=False)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 — codec exceptions are opaque
            self._stats.frames_failed += 1
            self._stats.consecutive_failures += 1
            fatal = self._stats.consecutive_failures >= self._MAX_CONSECUTIVE_FAILURES
            raise OpusDecodeError(
                f"opus decode failed: {type(exc).__name__}: {exc}",
                fatal=fatal,
            ) from exc

        if len(pcm_bytes) != SAMPLES_PER_FRAME * 2:
            self._stats.frames_failed += 1
            raise OpusDecodeError(
                f"opus decode produced {len(pcm_bytes)} bytes, expected {SAMPLES_PER_FRAME * 2}",
            )

        pcm = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        self._stats.frames_ok += 1
        self._stats.consecutive_failures = 0
        return pcm

    @property
    def consecutive_failures(self) -> int:
        return self._stats.consecutive_failures

    @property
    def frames_ok(self) -> int:
        return self._stats.frames_ok

    @property
    def frames_failed(self) -> int:
        return self._stats.frames_failed
