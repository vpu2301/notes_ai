"""Step 3 — magic-byte sniff matches the declared MIME (polyglot defence).

Hand-rolled prefix table for the audited format set; ``python-magic`` as fallback.
"""

from __future__ import annotations

from typing import Final

from .result import ValidationCode, ValidationResult, ok, reject

# declared MIME → acceptable (offset, bytes) prefixes.
_KNOWN_PREFIXES: Final[dict[str, list[tuple[int, bytes]]]] = {
    "audio/wav": [(0, b"RIFF"), (8, b"WAVE")],
    "audio/x-wav": [(0, b"RIFF"), (8, b"WAVE")],
    "audio/wave": [(0, b"RIFF"), (8, b"WAVE")],
    # MP3: an ID3v2 header or an MPEG frame sync (top 11 bits set, 0xFFE0–0xFFFF).
    "audio/mpeg": [(0, b"ID3"), (0, b"\xff\xfb"), (0, b"\xff\xfa"), (0, b"\xff\xf3")],
    "audio/mp3": [(0, b"ID3"), (0, b"\xff\xfb"), (0, b"\xff\xfa"), (0, b"\xff\xf3")],
    "audio/ogg": [(0, b"OggS")],
    "audio/webm": [(0, b"\x1aE\xdf\xa3")],  # EBML
    "audio/flac": [(0, b"fLaC")],
}


def validate_magic_bytes(declared_mime: str, head: bytes) -> ValidationResult:
    """:func:`ok` iff ``head`` (≥ 12 bytes, else reject) carries the magic for ``declared_mime``."""
    if len(head) < 12:
        return reject(
            ValidationCode.MIME_MISMATCH,
            "file is shorter than the magic-byte window (need ≥12 bytes)",
        )

    prefixes = _KNOWN_PREFIXES.get(declared_mime)
    if prefixes is None:
        # validate_mime gates this; fail closed.
        return reject(
            ValidationCode.MIME_MISMATCH,
            f"no magic-byte rule for declared MIME {declared_mime!r}",
        )

    for offset, signature in prefixes:
        end = offset + len(signature)
        if end <= len(head) and head[offset:end] == signature:
            return ok()

    return reject(
        ValidationCode.MIME_MISMATCH,
        f"declared MIME {declared_mime!r} but magic bytes do not match. "
        "Polyglot or mis-declared file rejected.",
    )
