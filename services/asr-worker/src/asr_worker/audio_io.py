"""ffmpeg decoding to 16 kHz PCM; argument-array form only, killed on timeout/cancel."""

from __future__ import annotations

import asyncio
import logging

import numpy as np

logger = logging.getLogger(__name__)


class AudioDecodeError(Exception):
    pass


async def decode_to_pcm(
    audio_bytes: bytes,
    *,
    ffmpeg_path: str = "ffmpeg",
    sample_rate: int = 16_000,
    timeout_seconds: float = 30.0,
    channels: int = 1,
) -> np.ndarray:
    """Return 16 kHz PCM: ``channels=1`` mono float32 1-D; ``channels=2`` int16 ``(n, 2)``,
    ch0 = microphone, ch1 = call audio (int16 to halve memory on long calls).
    """
    if channels not in (1, 2):
        raise ValueError("channels must be 1 or 2")
    args = [
        ffmpeg_path,
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-f",
        "f32le" if channels == 1 else "s16le",
        "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=audio_bytes), timeout=timeout_seconds
        )
    except TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise AudioDecodeError("ffmpeg decode timed out") from exc

    if proc.returncode != 0:
        raise AudioDecodeError(
            f"ffmpeg failed (rc={proc.returncode}): {stderr.decode('utf-8', 'replace')[:512]}"
        )

    if not stdout:
        raise AudioDecodeError("ffmpeg produced zero PCM samples")

    if channels == 2:
        # Read-only view over ffmpeg's buffer; no second copy.
        stereo = np.frombuffer(stdout, dtype=np.int16)
        return stereo[: len(stereo) // 2 * 2].reshape(-1, 2)
    pcm = np.frombuffer(stdout, dtype=np.float32).copy()
    return pcm


_MIX_BLOCK = 16_000 * 60  # one minute at a time: no full-length temporaries


def mixdown(stereo: np.ndarray) -> np.ndarray:
    """(n, 2) int16 → mono float32, what ASR hears (one pass, unchanged)."""
    out = np.empty(stereo.shape[0], dtype=np.float32)
    for start in range(0, stereo.shape[0], _MIX_BLOCK):
        block = stereo[start : start + _MIX_BLOCK].astype(np.float32)
        out[start : start + _MIX_BLOCK] = (block[:, 0] + block[:, 1]) / 65536.0
    return out
