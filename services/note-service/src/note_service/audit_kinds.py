"""Audit kinds emitted by note-service. See docs/audit/event-kinds.md."""

from __future__ import annotations

from typing import Final

TEMPLATE_CREATED: Final = "template.created"  # plain POST /templates (M1·A4)
TEMPLATE_CLONED: Final = "template.cloned"
TEMPLATE_UPDATED: Final = "template.updated"  # cosmetic edit
TEMPLATE_VERSIONED: Final = "template.versioned"  # structural edit → new row
TEMPLATE_DEPRECATED: Final = "template.deprecated"  # soft-delete
TEMPLATE_VIEWED_FULL: Final = "template.viewed_full"  # GET /templates/{id}
TEMPLATE_REBOUND: Final = "template.rebound"  # sprint-17: draft moved to successor

# Sprint-08: notes slice.
NOTE_CREATED: Final = "note.created"
NOTE_DRAFT_UPDATED: Final = "note.draft.updated"  # aggregated per session
NOTE_FINALIZED: Final = "note.finalized"
NOTE_COMPLETED: Final = "note.completed"  # finalize completion summary (M1·A5)
NOTE_REVERTED: Final = "note.reverted"
NOTE_CANCELLED: Final = "note.cancelled"
NOTE_AMENDED: Final = "note.amended"  # finalized → amended (versioned amendment)
NOTE_VIEWED_FULL: Final = "note.viewed_full"  # carries purpose
NOTE_SEARCHED: Final = "note.searched"
NOTE_CHAIN_INTEGRITY_FAILURE: Final = "note.chain_integrity_failure"
NOTE_PDF_RENDERED: Final = "note.pdf_rendered"  # GET /notes/{id}/pdf (M1·A3)

# 0016: delete, visibility, sharing.
NOTE_DELETED: Final = "note.deleted"  # soft delete (bin); links revoked
NOTE_VISIBILITY_CHANGED: Final = "note.visibility_changed"  # private ↔ workspace
NOTE_SHARED: Final = "note.shared"  # a member was given read access
NOTE_UNSHARED: Final = "note.unshared"
NOTE_LINK_CREATED: Final = "note.link_created"  # public "anyone with the link"
NOTE_LINK_REVOKED: Final = "note.link_revoked"
NOTE_VIEWED_VIA_LINK: Final = "note.viewed_via_link"  # anonymous read

# Spec item 1: note synthesis (raw dictation → clean prose).
NOTE_SYNTHESIS_STARTED: Final = "note.synthesis_started"
NOTE_SYNTHESIS_COMPLETED: Final = "note.synthesis_completed"

# Sprint-13: typed fields. Both are the extractor-quality
# feedback loop (step 08's override-rate dashboard).
#
# CONTENT RULE: payloads carry the section id, the field type and — only
# for closed vocabularies — the option slug. Free-text values are NEVER
# included; a "what did they change it to" payload over prose would put
# note content in the audit chain. Test-enforced.
# Emitted ONCE per finalized note, summarising how many typed fields
# carried machine-extracted values at the moment of finalize. Aggregated
# on purpose: a row per utterance would be audit-chain pollution.
FIELD_EXTRACTED: Final = "note.field.extracted"
FIELD_CONFIRMED: Final = "note.field.confirmed"
FIELD_OVERRIDDEN: Final = "note.field.overridden"

# ── S15: audio replay (ADR-0037) ─────────────────────────────────────
# One event per clip created — replay is a per-decision review act, not
# a keystroke stream, so no aggregation. Payload: clip_id, source_kind,
# ms range, purpose, is_author. Never transcript text.
NOTE_AUDIO_REPLAYED: Final = "note.audio_replayed"

# ── S15: query expansion (ADR-0038) ──────────────────────────────────
# search.expanded is AGGREGATED (one row per tenant per flush interval;
# payload: count, expanded_terms_total — never the query text). The
# synonym.group.* kinds fire per curation act; terms are dictionary
# entries, not prose.
SEARCH_EXPANDED: Final = "search.expanded"
SYNONYM_GROUP_CREATED: Final = "synonym.group.created"
SYNONYM_GROUP_UPDATED: Final = "synonym.group.updated"
SYNONYM_GROUP_DELETED: Final = "synonym.group.deleted"

# ── 0019: calendar connections ──────────────────────────────────────
# Payload: provider and the connection id — never the account's
# e-mail, and never an event title.
CALENDAR_CONNECTED: Final = "calendar.connected"
CALENDAR_DISCONNECTED: Final = "calendar.disconnected"

# ── Sprint 16 — scheduler runs ──────────────────────────────────────────
SCHEDULER_JOB_COMPLETED: Final = "scheduler.job.completed"
SCHEDULER_JOB_FAILED: Final = "scheduler.job.failed"
