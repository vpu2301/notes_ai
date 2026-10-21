"""Note-generation counters. Counts only; labels are closed vocabularies or backend
names, never content or a tenant id.
"""

from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("mdx.note.generation")

generations = _meter.create_counter(
    "mdx_note_generations_total",
    description="Finished generations (labels: outcome, backend)",
    unit="1",
)
generation_seconds = _meter.create_histogram(
    "mdx_note_generation_seconds_histogram",
    description="Wall time of a generation, end to end",
    unit="s",
)
snapshots_swept = _meter.create_counter(
    "mdx_note_generation_snapshots_swept_total",
    description="Transcript snapshots deleted by the daily sweep",
    unit="1",
)
budget_blocked = _meter.create_counter(
    "mdx_note_generation_budget_blocked_total",
    description="Generations not enqueued (labels: reason)",
    unit="1",
)

# ── Every written line is a row ─────────────────────────────────────
lines_stored = _meter.create_counter(
    "mdx_note_generation_lines_stored_total",
    description="Written lines stored with their evidence (labels: kind)",
    unit="1",
)
dates_exported = _meter.create_counter(
    "mdx_note_dates_exported_total",
    description="Key dates downloaded as a calendar file",
    unit="1",
)
corrections_counter = _meter.create_counter(
    "mdx_note_corrections_total",
    description="Name corrections the author acted on (labels: action = accepted|rejected)",
    unit="1",
)
