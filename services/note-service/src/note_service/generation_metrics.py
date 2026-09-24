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

# ── What the engine wrote and left out (Summary Engine v2, Q2) ──────
# Closed vocabularies only. A line's text, a fact, a quote never becomes
# a label; these say how many, and why.
lines = _meter.create_counter(
    "mdx_note_generation_lines_total",
    description="Composed lines by gate outcome (labels: outcome = kept|unsupported|number|name|example)",
    unit="1",
)
noise = _meter.create_counter(
    "mdx_note_generation_noise_total",
    description="Noise flags by outcome (labels: outcome = confirmed|advisory|overridden)",
    unit="1",
)
facts = _meter.create_counter(
    "mdx_note_generation_facts_total",
    description=(
        "Extracted facts by outcome (labels: outcome = kept|dropped_quote|dropped_noise|"
        "dropped_paraphrase|flagged_paraphrase)"
    ),
    unit="1",
)
excluded_share = _meter.create_histogram(
    "mdx_note_generation_excluded_share",
    description="Share of speech time left out of a generation as noise (0..1)",
    unit="1",
)


def record_document(stats: dict, *, backend: str) -> None:
    """The per-generation counts of a finished document. Counts only."""
    for outcome in ("unsupported", "number", "name", "example"):
        n = int((stats.get("lines_unsupported") or {}).get(outcome, 0))
        if n:
            lines.add(n, {"outcome": outcome})
    if stats.get("lines_kept"):
        lines.add(int(stats["lines_kept"]), {"outcome": "kept"})
    confirmed = int(stats.get("noise_confirmed", 0)) - int(stats.get("noise_overridden", 0))
    for outcome, n in (
        ("confirmed", confirmed),
        ("advisory", int(stats.get("noise_advisory", 0))),
        ("overridden", int(stats.get("noise_overridden", 0))),
    ):
        if n > 0:
            noise.add(n, {"outcome": outcome})
    for outcome, key in (
        ("kept", "facts_kept"),
        ("dropped_quote", "facts_dropped_quote"),
        ("dropped_noise", "facts_dropped_noise"),
        ("dropped_paraphrase", "facts_dropped_paraphrase"),
        ("flagged_paraphrase", "facts_flagged_paraphrase"),
    ):
        n = int(stats.get(key, 0))
        if n:
            facts.add(n, {"outcome": outcome})
    for source, n in (stats.get("entities_corrected") or {}).items():
        if n:
            entities_counter.add(int(n), {"outcome": f"corrected_{source}"})
    for outcome, key in (
        ("marked", "entities_marked"),
        ("model_failed", "entities_model_failed"),
        ("attribution_missing", "attribution_missing"),
    ):
        if stats.get(key):
            entities_counter.add(int(stats[key]), {"outcome": outcome})
    if stats.get("redundant_lines"):
        redundant_lines.add(int(stats["redundant_lines"]))
    speech = int(stats.get("speech_ms", 0))
    if speech > 0:
        excluded_share.record(int(stats.get("excluded_ms", 0)) / speech, {"backend": backend})


# ── Q3: what the recording is, and what the render removed ─────────
classify = _meter.create_counter(
    "mdx_note_generation_classify_total",
    description="How a generation's recording type was decided (labels: outcome = user|classifier|rule|failed)",
    unit="1",
)
redundant_lines = _meter.create_counter(
    "mdx_note_generation_redundant_lines_total",
    description="Lines the render left out because another line already says them",
    unit="1",
)

# ── Q4: names respelled, doubted, and opinions without a holder ─────
entities_counter = _meter.create_counter(
    "mdx_note_generation_entities_total",
    description=(
        "Names in generated lines by outcome (labels: outcome = corrected_glossary|"
        "corrected_candidate|corrected_model|marked|model_failed|attribution_missing)"
    ),
    unit="1",
)

# ── Q5: every written line is a row ─────────────────────────────────
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
