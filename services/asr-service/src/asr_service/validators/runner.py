"""Run validators 2–7 (pure file-shape checks); auth and quota run at the router."""

from __future__ import annotations

import contextlib
import os
import tempfile
from dataclasses import replace

from ..config import settings
from .codec import validate_codec
from .duration import probe_audio, validate_duration
from .hash import compute_hash
from .magic_bytes import validate_magic_bytes
from .mime import normalize_mime, validate_mime
from .result import UploadFacts, ValidationResult, ok
from .size import validate_size


async def run_all(
    *,
    mime_type: str,
    payload: bytes,
) -> tuple[ValidationResult, UploadFacts]:
    """Run steps 2–7; returns the result plus the facts collected so far."""
    r = validate_mime(mime_type)

    # Everything downstream keys off the bare type/subtype.
    mime_type = normalize_mime(mime_type)
    facts = UploadFacts(
        mime_type=mime_type,
        size_bytes=len(payload),
        bytes_buffer=payload,
    )

    if not r.ok:
        return r, facts

    # Size before magic bytes: it owns the zero-byte case.
    r = validate_size(len(payload), max_mb=settings.max_upload_mb)
    if not r.ok:
        return r, facts

    r = validate_magic_bytes(mime_type, payload[:64])
    if not r.ok:
        return r, facts

    with tempfile.NamedTemporaryFile(
        prefix="mdx-asr-",
        suffix=_mime_to_suffix(mime_type),
        delete=False,
    ) as tmp:
        tmp.write(payload)
        tmp_path = tmp.name

    try:
        probe = await probe_audio(
            tmp_path,
            ffprobe_path=settings.ffprobe_path,
            timeout_seconds=settings.ffprobe_timeout_seconds,
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)

    r = validate_duration(
        probe,
        max_seconds=settings.max_duration_seconds,
        min_ms=settings.min_duration_ms,
    )
    if not r.ok or probe is None:
        return r, facts

    facts = replace(
        facts,
        duration_ms=probe.duration_ms,
        sample_rate_hz=probe.sample_rate_hz,
        channels=probe.channels,
        codec=probe.codec,
    )

    r = validate_codec(
        probe,
        min_sample_rate_hz=settings.min_sample_rate_hz,
        max_channels=settings.max_channels,
    )
    if not r.ok:
        return r, facts

    facts = replace(facts, sha256=compute_hash(payload))
    return ok(), facts


def _mime_to_suffix(mime: str) -> str:
    return {
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/wave": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/ogg": ".ogg",
        "audio/webm": ".webm",
        "audio/flac": ".flac",
    }.get(mime, ".bin")
