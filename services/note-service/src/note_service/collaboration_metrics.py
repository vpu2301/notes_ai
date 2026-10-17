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
