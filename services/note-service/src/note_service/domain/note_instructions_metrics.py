"""Note instructions metrics (N1). Labels are closed vocabularies; never text."""

from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("mdx.note.instructions")

compiles = _meter.create_counter(
    "mdx_note_instructions_compiles_total",
    description="Instruction compiles by outcome (compiled|failed) and kind (save|preview)",
    unit="1",
)
compile_seconds = _meter.create_histogram(
    "mdx_note_instructions_compile_seconds",
    description="Time of one instruction compile, by outcome",
    unit="s",
)
not_applied = _meter.create_counter(
    "mdx_note_instructions_not_applied_total",
    description="Requests the compiler did not apply, by reason",
    unit="1",
)
previews_limited = _meter.create_counter(
    "mdx_note_instructions_previews_limited_total",
    description="Previews refused by the per-workspace hourly cap",
    unit="1",
)
