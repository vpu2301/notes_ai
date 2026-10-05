"""Audit event kinds emitted by nlp-service. See docs/audit/event-kinds.md."""

from __future__ import annotations

from typing import Final

# Emitted by the frontend via POST /audit/events/voice_command_*, never by nlp-service.
VOICE_COMMAND_EXECUTED: Final = "voice_command.executed"
VOICE_COMMAND_UNDONE: Final = "voice_command.undone"
VOICE_COMMAND_EXECUTED_FAILED: Final = "voice_command.executed_failed"

# Admin actions on the abbreviation dictionary.
ABBREVIATION_POLICY_SET: Final = "abbreviation.policy.set"
ABBREVIATION_POLICY_DELETED: Final = "abbreviation.policy.deleted"

# Emitted by dictation-service when its NLP call times out.
DICTATION_NLP_TIMEOUT: Final = "dictation.nlp_timeout"
