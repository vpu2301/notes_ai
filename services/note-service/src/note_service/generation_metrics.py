"""Note-generation counters (Sprint 37).

Counts only, and no label that can carry content: `outcome` and
`error_kind` are closed vocabularies, `backend` is a name from
`config/models.yaml`. A quote, an item's text, a speaker or a tenant id
never becomes a label — the first three are content, the fourth is
unbounded cardinality.
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

# ── Shadow runs (B-1, before a routing flip) ────────────────────────
# A candidate backend runs on a sample of real meetings and its output is
# thrown away. Only these numbers survive it: never a second copy of the
# document, never a fact's text.
shadow_runs = _meter.create_counter(
    "mdx_note_generation_shadow_runs_total",
    description="Shadow generations (labels: backend, outcome)",
    unit="1",
)
shadow_facts = _meter.create_counter(
    "mdx_note_generation_shadow_facts_total",
    description="Facts the shadow backend kept or dropped (labels: backend, verdict)",
    unit="1",
)
shadow_seconds = _meter.create_histogram(
    "mdx_note_generation_shadow_seconds_histogram",
    description="Wall time of a shadow generation",
    unit="s",
)
