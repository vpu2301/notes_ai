"""Audit event kinds emitted by dictation-service. See docs/audit/event-kinds.md."""

from __future__ import annotations

from typing import Final

# Session lifecycle
SESSION_STARTED: Final = "dictation.session.started"
SESSION_RESUMED: Final = "dictation.session.resumed"
SESSION_FINALIZED: Final = "dictation.session.finalized"
SESSION_ABANDONED: Final = "dictation.session.abandoned"
SESSION_FAILED: Final = "dictation.session.failed"

# Audio
AUDIO_UPLOADED: Final = "dictation.audio.uploaded"
AUDIO_TRUNCATED: Final = "dictation.audio.truncated"  # severity=warn

# Upgrade rejections
UPGRADE_FAILED: Final = "dictation.upgrade.failed"  # warn/sec by cause

# Section-aware dictation
SECTION_SWITCHED: Final = "dictation.section_switched"

# NLP degradation
NLP_TIMEOUT: Final = "dictation.nlp_timeout"  # severity=warn

# Conversation mode (SESSION_STARTED carries `mode` in its payload)
SPEAKER_MAPPING_MANUAL_SET: Final = "conversation.speaker_mapping.manual_set"

# Draft creation on conversation finalize (via note-service POST /v1/notes)
DRAFT_CREATED: Final = "conversation.draft.created"
DRAFT_CREATE_FAILED: Final = "conversation.draft.create_failed"  # severity=warn
