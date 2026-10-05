"""Audit event kinds emitted by asr-worker."""

from __future__ import annotations

from typing import Final

TRANSCRIPTION_STARTED: Final = "asr.transcription_started"
TRANSCRIPTION_COMPLETE: Final = "asr.transcription_complete"
TRANSCRIPTION_FAILED: Final = "asr.transcription_failed"
JOB_CANCELLED: Final = "asr.job_cancelled"
# Speaker re-labelling. Payloads carry counts and the engine, never names or text.
REDIARIZE_COMPLETED: Final = "asr.rediarize_completed"
REDIARIZE_FAILED: Final = "asr.rediarize_failed"

# Emitted as a CRITICAL log, not an audit row: no tenant context yet (docs/audit/event-kinds.md).
KEY_MASTER_MISSING: Final = "asr.key.master_missing"  # severity=error
