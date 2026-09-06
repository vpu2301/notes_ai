"""Step 5 — probe duration with ffprobe; reject > MD_ASR_MAX_DURATION_SECONDS.

ffprobe is invoked with the strict ``-of json`` output and timeout. The
subprocess is started with the argument-array form (never a shell
string) so user-controlled bytes can never inject shell metacharacters.

The probe also returns the codec, sample rate, and channel count, which
the next validator (codec) consumes — kept in :class:`ProbeOutput` to
avoid running ffprobe twice.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from .result import ValidationCode, ValidationResult, ok, reject

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProbeOutput:
    duration_ms: int
    sample_rate_hz: int
    channels: int
    codec: str


async def probe_audio(
    path: str,
    *,
    ffprobe_path: str = "ffprobe",
    timeout_seconds: float = 5.0,
) -> ProbeOutput | None:
    """Run ffprobe on the file and return parsed metadata.

    Returns ``None`` if the file is unprobeable (corrupt headers, codec
    we don't recognise, or ffprobe times out / crashes).
    """
    args = [
        ffprobe_path,
        "-v",
        "error",
        "-show_streams",
        "-select_streams",
        "a:0",
        "-show_format",
        "-of",
        "json",
        path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            logger.info("ffprobe.timeout", extra={"path": path})
            return None
    except FileNotFoundError:
        logger.error("ffprobe.not_found", extra={"ffprobe_path": ffprobe_path})
        return None

    if proc.returncode != 0:
        return None

    try:
        doc = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    fmt = doc.get("format", {})
    streams = doc.get("streams") or []
    if not streams:
        return None
    stream = streams[0]

    try:
        duration_seconds = float(stream.get("duration") or fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        return None

    sample_rate = int(stream.get("sample_rate", 0))
    channels = int(stream.get("channels", 0))
    codec = str(stream.get("codec_name", ""))

    if sample_rate <= 0 or channels <= 0 or not codec:
        return None

    # A WebM written live — which is every ``MediaRecorder`` capture, and
    # the shape the web and mobile clients upload — carries no duration
    # in its header: the muxer never seeks back to fill it in. Neither
    # the format nor the stream reports one, so the header pass yields 0
    # and the file would look unprobeable. Walking the packets recovers
    # the real length (~0.2 s for a 30-minute recording).
    if duration_seconds <= 0:
        duration_seconds = await _duration_from_packets(
            path, ffprobe_path=ffprobe_path, timeout_seconds=timeout_seconds
        )
        if duration_seconds <= 0:
            return None

    return ProbeOutput(
        duration_ms=int(duration_seconds * 1000),
        sample_rate_hz=sample_rate,
        channels=channels,
        codec=codec,
    )


async def _duration_from_packets(
    path: str,
    *,
    ffprobe_path: str,
    timeout_seconds: float,
) -> float:
    """Duration of the first audio stream, summed from its packets.

    Used only when the container declares none. Returns ``0.0`` if the
    scan fails, which the caller treats as unprobeable.
    """
    args = [
        ffprobe_path,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "packet=pts_time,duration_time",
        "-of",
        "csv=p=0",
        path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            logger.info("ffprobe.packet_scan_timeout", extra={"path": path})
            return 0.0
    except FileNotFoundError:
        return 0.0

    if proc.returncode != 0:
        return 0.0

    # The end of the last packet that carries a timestamp. Trailing
    # packets can report "N/A" for either field, so scan backwards for
    # the last usable pair rather than trusting the final line.
    for line in reversed(stdout.decode("utf-8", "replace").splitlines()):
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            return float(parts[0]) + float(parts[1])
        except ValueError:
            continue
    return 0.0


def validate_duration(
    probe: ProbeOutput | None, *, max_seconds: int, min_ms: int = 0
) -> ValidationResult:
    if probe is None:
        return reject(
            ValidationCode.UNPROBEABLE,
            "ffprobe could not probe the audio (corrupt header, unsupported "
            "container, or process timed out).",
        )
    # A recording too short to hold a usable utterance is a mis-fire — a
    # tapped record button, a browser that flushed one buffer. Whisper will
    # happily "transcribe" it into a hallucinated phrase, which is worse
    # than a rejection: it lands in the note looking like dictation.
    if probe.duration_ms < min_ms:
        return reject(
            ValidationCode.DURATION_TOO_SHORT,
            f"audio is {probe.duration_ms} ms; the minimum is {min_ms} ms",
        )
    if probe.duration_ms <= max_seconds * 1000:
        return ok()
    return reject(
        ValidationCode.DURATION_EXCEEDED,
        f"audio is {probe.duration_ms / 1000:.1f}s; cap is {max_seconds}s",
    )
