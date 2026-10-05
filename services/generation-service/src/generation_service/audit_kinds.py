"""Audit event kinds emitted by generation-service (docs/audit/event-kinds.md)."""

from __future__ import annotations

from typing import Final

# Aggregated per tenant per flush interval (payload {"count": n}).
LAYER_C_COMPLETION_SHOWN: Final = "layer_c.completion.shown"
# Warn, immediate: safety filter dropped a completion introducing a value not in the typed text.
LAYER_C_COMPLETION_FILTERED: Final = "layer_c.completion.filtered"
