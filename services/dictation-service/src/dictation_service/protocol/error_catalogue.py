"""Stable, public error codes for the dictation wire protocol; codes may be added, never renamed."""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ErrorCode(StrEnum):
    # 4xx-ish (caller fault, non-recoverable in-session)
    BAD_MESSAGE = "bad_message"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    AUTH_INVALID = "auth_invalid"
    PAUSE_STATE_MISMATCH = "pause_state_mismatch"
    RETRANSMIT_TOO_LARGE = "retransmit_too_large"
    SESSION_NOT_FOUND = "session_not_found"
    RATE_LIMITED = "rate_limited"

    # 5xx-ish (server side)
    WORKER_FAILED = "worker_failed"
    AUDIO_DECODE_FAILED = "audio_decode_failed"
    GPU_FULL = "gpu_full"
    GAP_DETECTED = "gap_detected"
    HIGH_LATENCY = "high_latency"
    WORKER_OVERLOADED = "worker_overloaded"
    LOW_CONFIDENCE = "low_confidence"
    TOKEN_EXPIRED = "token_expired"
    INTERNAL = "internal"


# Recoverable: retry/reconnect/resume can recover. Otherwise the session is over.
RECOVERABLE: Final[frozenset[ErrorCode]] = frozenset(
    {
        ErrorCode.BAD_MESSAGE,
        ErrorCode.AUDIO_DECODE_FAILED,
        ErrorCode.GAP_DETECTED,
        ErrorCode.HIGH_LATENCY,
        ErrorCode.WORKER_OVERLOADED,
        ErrorCode.LOW_CONFIDENCE,
        ErrorCode.GPU_FULL,  # retry later
        ErrorCode.RATE_LIMITED,
        ErrorCode.RETRANSMIT_TOO_LARGE,
    }
)


def is_recoverable(code: ErrorCode | str) -> bool:
    try:
        return ErrorCode(code) in RECOVERABLE
    except ValueError:
        return False
