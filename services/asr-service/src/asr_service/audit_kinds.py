"""ASR-related audit event kinds. See docs/audit/event-kinds.md."""

from __future__ import annotations

from typing import Final

# Audio lifecycle
AUDIO_UPLOADED: Final = "asr.audio_uploaded"
AUDIO_DELETED: Final = "asr.audio_deleted"

# Job lifecycle
JOB_QUEUED: Final = "asr.job_queued"
TRANSCRIPTION_STARTED: Final = "asr.transcription_started"
TRANSCRIPTION_COMPLETE: Final = "asr.transcription_complete"
TRANSCRIPTION_FAILED: Final = "asr.transcription_failed"
TRANSCRIPT_ACCESSED: Final = "asr.transcript_accessed"
JOB_CANCELLED: Final = "asr.job_cancelled"
# Someone named (or renamed) the diarized speakers of a job.
SPEAKERS_NAMED: Final = "asr.speakers_named"
# Speaker edit overlay (Sprint 28): labels only, never names.
SPEAKERS_MERGED: Final = "asr.speakers_merged"
SPEAKER_EDIT_REVERTED: Final = "asr.speaker_edit_reverted"
# Turn-level correction (Sprint 30): counts and target kind only.
TURN_REASSIGNED: Final = "asr.turn_reassigned"
SPEAKER_EDITS_RESET: Final = "asr.speaker_edits_reset"
# Name suggestions (Sprint 32): the label only, never the name.
NAME_SUGGESTION_ACCEPTED: Final = "asr.name_suggestion_accepted"
NAME_SUGGESTION_DISMISSED: Final = "asr.name_suggestion_dismissed"
# Speaker re-labelling (Sprint 29). The worker emits
# asr.rediarize_completed / asr.rediarize_failed; the reaper emits the
# latter for a stranded re-run. Payloads: hint kind, counts, engine.
REDIARIZE_REQUESTED: Final = "asr.rediarize_requested"
REDIARIZE_UNDONE: Final = "asr.rediarize_undone"
REDIARIZE_FAILED: Final = "asr.rediarize_failed"

# Spelling overlay (Sprint TQ3): counts, source, status — never the text.
TRANSCRIPT_CORRECTION_PROPOSED: Final = "asr.transcript_correction_proposed"
TRANSCRIPT_CORRECTION_ACCEPTED: Final = "asr.transcript_correction_accepted"
TRANSCRIPT_CORRECTION_REJECTED: Final = "asr.transcript_correction_rejected"

# Quota
QUOTA_EXCEEDED: Final = "asr.quota_exceeded"  # severity=warn
