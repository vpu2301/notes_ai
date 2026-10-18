"""Collaboration instruments (W3): comments and presence. Module level, so routers
need nothing wired into state. Labels are closed vocabularies; never a sub or a body.
"""

from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("mdx.note.collaboration")

comments_created = _meter.create_counter(
    "mdx_note_comments_total",
    description="Comments posted on notes (label: anchor_kind)",
    unit="1",
)
presence_viewers = _meter.create_histogram(
    "mdx_note_presence_viewers",
    description="Other people viewing a note, per presence read",
    unit="1",
)

# W3: writes refused because the caller's level on the note was too low. A spike on
# `required="edit"` means a client offers editing to people who may only comment or view.
access_refused = _meter.create_counter(
    "mdx_note_access_refused_total",
    description="Note writes refused for an insufficient level (label: level_required)",
    unit="1",
)

# W5: the workspace is the folder. `source` author|backfill|move; `to` private|workspace.
visibility_changed = _meter.create_counter(
    "mdx_note_visibility_changed_total",
    description="Note visibility changes (labels: source, to)",
    unit="1",
)
visibility_backfill = _meter.create_counter(
    "mdx_note_visibility_backfill_total",
    description="W5 backfill outcomes per note (label: outcome changed|sensitive|author_choice)",
    unit="1",
)
note_moves = _meter.create_counter(
    "mdx_note_move_total",
    description="Moves between workspaces (labels: result moved|refused, reason)",
    unit="1",
)
note_copies = _meter.create_counter(
    "mdx_note_copy_total",
    description="Copies into another workspace (label: result)",
    unit="1",
)
rehome_total = _meter.create_counter(
    "mdx_note_rehome_total",
    description="Media re-home jobs of moved notes (label: result done|retry|dead)",
    unit="1",
)
rehome_bytes = _meter.create_histogram(
    "mdx_note_rehome_bytes",
    description="Plaintext bytes re-encrypted per re-home",
    unit="By",
)
rehome_seconds = _meter.create_histogram(
    "mdx_note_rehome_seconds",
    description="Move to media ready, per re-home (SLO p95 < 90 s)",
    unit="s",
)
