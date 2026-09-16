"""PCM ⇄ WAV helpers shared by the HTTP ASR provider and the eval scripts."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000


def pcm_to_wav_bytes(pcm: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """float32 [-1, 1] mono → 16-bit PCM WAV bytes."""
    clipped = np.clip(np.asarray(pcm, dtype=np.float32), -1.0, 1.0)
    int16 = (clipped * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(int16.tobytes())
    return buf.getvalue()


def wav_file_to_pcm(path: str | Path) -> np.ndarray:
    """16-bit mono WAV → float32 PCM. Rejects anything that is not 16 kHz mono 16-bit."""
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != SAMPLE_RATE:
            raise ValueError(
                f"{path}: need 16 kHz mono 16-bit WAV, got {w.getframerate()} Hz, "
                f"{w.getnchannels()} ch, {w.getsampwidth() * 8}-bit"
            )
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0


def probe_clip_path() -> Path:
    """A ~2 s spoken clip bundled with the package (used by ``asr_http`` probes)."""
    return Path(__file__).with_name("probe_clip.wav")
