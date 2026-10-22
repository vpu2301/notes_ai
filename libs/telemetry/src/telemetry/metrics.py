"""Prometheus aggregates for telemetry — low-cardinality labels only (stage, backend, status,
kind, provider, model_family, purpose, direction, source, entity). Run, recording, job and
tenant ids never become labels; they live in the per-run rows and in traces."""

from __future__ import annotations

import re

from opentelemetry import metrics

_meter = metrics.get_meter("mdx.telemetry")

# Seconds to tens of minutes: a model load, a 2-hour recording's ASR, an LLM window.
_SECONDS_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1200, 2400, 3600)

stage_seconds = _meter.create_histogram(
    "mdx_pipeline_stage_seconds",
    description="Duration of one pipeline stage span, by stage, backend and status",
    unit="s",
    explicit_bucket_boundaries_advisory=_SECONDS_BUCKETS,
)
runs_total = _meter.create_counter(
    "mdx_pipeline_runs_total",
    description="Processing runs finished, by kind and status",
    unit="1",
)
llm_calls_total = _meter.create_counter(
    "mdx_llm_calls_total",
    description="LLM calls recorded by telemetry, by provider, model family, purpose and status",
    unit="1",
)
llm_tokens_total = _meter.create_counter(
    "mdx_llm_tokens_total",
    description="LLM tokens by provider, model family, direction (input|output|cached|reasoning) and source",
    unit="1",
)
write_errors_total = _meter.create_counter(
    "mdx_telemetry_write_errors_total",
    description="Telemetry writes that failed and were dropped (fail-open), by entity",
    unit="1",
)


def model_family(model: str | None) -> str:
    """A bounded label from a model id: its leading word (``mistral-large-2512`` → ``mistral``,
    ``gemma3:1b`` → ``gemma``)."""
    base = (model or "").rsplit("/", 1)[-1].lower()
    head = re.split(r"[:\-_.\d]", base, maxsplit=1)[0]
    return head[:32] or "unknown"
