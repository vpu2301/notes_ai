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
NOTE_CANCELLED: Final = "note.cancelled"
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
# The note was mailed to somebody, from the server. Counts only — the
# addresses stay out of the audit log on purpose.
NOTE_LINK_EMAILED: Final = "note.link_emailed"
NOTE_VIEWED_VIA_LINK: Final = "note.viewed_via_link"  # anonymous read
# Sprint 19: the recipient clicked the shared page's "create your own
# workspace" CTA. Payload: link_id only — the recipient is unknown by design.
NOTE_CTA_CLICKED: Final = "note.cta_clicked"
# Sprint 20: the recipient acted on the shared page. Payload: link_id,
# kind (closed vocab), target (item|section) — never the comment or a key.
NOTE_RECIPIENT_RESPONDED: Final = "note.recipient_responded"
NOTE_ITEM_STATUS_CHANGED: Final = "note.item_status_changed"  # item_key, from, to
NOTE_RESPONSE_CLEARED: Final = "note.response_cleared"  # kind
# Sprint 22: the product mailed a recipient link. Payload: link_id,
# resend, outcome (sent|failed). Never the address.
NOTE_LINK_SENT: Final = "note.link_sent"
# The recipient opted out of mail from every workspace. Payload: link_id.
NOTE_RECIPIENT_UNSUBSCRIBED: Final = "note.recipient_unsubscribed"
# Sprint 23: policy, verification, abuse.
TENANT_SHARING_POLICY_CHANGED: Final = "tenant.sharing_policy_changed"  # changed_keys
NOTE_RECIPIENT_VERIFICATION_REQUESTED: Final = "note.recipient_verification_requested"  # link_id
NOTE_RECIPIENT_VERIFIED: Final = "note.recipient_verified"  # link_id
NOTE_LINK_REPORTED: Final = "note.link_reported"  # link_id, reason

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
# `note.field.extracted` (one aggregated row per finalize) retired with
# the finalize lifecycle (migration 0042).
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

# ── 0021: spaces (personal note folders) ────────────────────────────
# Payload: the space id only — never its name, never a note title.
# Filing a note is not audited (frequent, and it changes nothing about
# the note itself).
SPACE_CREATED: Final = "space.created"
SPACE_RENAMED: Final = "space.renamed"
SPACE_DELETED: Final = "space.deleted"

# ── Sprint 16 — scheduler runs ──────────────────────────────────────────
SCHEDULER_JOB_COMPLETED: Final = "scheduler.job.completed"
SCHEDULER_JOB_FAILED: Final = "scheduler.job.failed"

# "Ask this note": a question answered by the model over the note + transcript.
NOTE_ASKED: Final = "note.asked"  # payload: backend, model_id, question_chars — never the text
