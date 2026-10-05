"""Silero VAD for diarization: unlike ``asr_worker.vad`` it never merges across a turn change and has NO stub fallback."""

from __future__ import annotations

from typing import Any

import numpy as np

SAMPLE_RATE_HZ = 16_000


class SileroSegmenter:
    """Speech-region detection over a PCM window; one call at a time per process (state reset per invocation)."""

    def __init__(
        self,
        *,
        min_speech_duration_ms: int = 150,
        min_silence_duration_ms: int = 150,
        threshold: float | None = None,
    ) -> None:
        # None = silero-vad's own default (0.5).
        self._threshold = threshold
        self._min_speech_ms = min_speech_duration_ms
        self._min_silence_ms = min_silence_duration_ms
        self._model: Any = None
        self._get_speech_timestamps: Any = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad

        torch.set_grad_enabled(False)
        self._model = load_silero_vad()
        self._get_speech_timestamps = get_speech_timestamps

    def speech_regions(self, pcm: np.ndarray) -> list[tuple[int, int]]:
        """[(start_ms, end_ms), ...] of speech inside ``pcm`` (float32 mono 16 kHz), relative to the buffer start."""
        self._ensure_loaded()
        import torch

        if pcm.size == 0:
            return []
        tensor = torch.from_numpy(np.ascontiguousarray(pcm, dtype=np.float32))
        stamps = self._get_speech_timestamps(
            tensor,
            self._model,
            sampling_rate=SAMPLE_RATE_HZ,
            min_speech_duration_ms=self._min_speech_ms,
            min_silence_duration_ms=self._min_silence_ms,
            **({"threshold": self._threshold} if self._threshold is not None else {}),
        )
        return [
            (
                int(s["start"] * 1000 / SAMPLE_RATE_HZ),
                int(s["end"] * 1000 / SAMPLE_RATE_HZ),
            )
            for s in stamps
        ]
