"""OpenTelemetry instruments for the job queue and the model backends (DEP-S1 §S).

Names are referenced by infra/prometheus/rules/model-backends.yml — keep stable.
"""

from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("mdx.jobs")

jobs_claimed_total = _meter.create_counter(
    "mdx_jobs_claimed_total", description="Jobs claimed by a runner, by kind", unit="1"
)
jobs_finished_total = _meter.create_counter(
    "mdx_jobs_finished_total",
    description="Jobs reaching a terminal or retry state, by kind and outcome",
    unit="1",
)
jobs_processing_seconds = _meter.create_histogram(
    "mdx_jobs_processing_seconds", description="Wall time of one job attempt", unit="s"
)
jobs_queued_age_seconds = _meter.create_histogram(
    "mdx_jobs_queued_age_seconds",
    description="Age of a job when claimed (run_at → claim)",
    unit="s",
)
jobs_reaped_total = _meter.create_counter(
    "mdx_jobs_reaped_total",
    description="Running jobs re-queued or killed by the stale-lease reaper",
    unit="1",
)

model_calls_total = _meter.create_counter(
    "mdx_model_calls_total",
    description="Model backend calls by backend, operation and outcome",
    unit="1",
)
model_latency_seconds = _meter.create_histogram(
    "mdx_model_latency_seconds", description="Model backend call latency by backend", unit="s"
)
model_cold_starts_total = _meter.create_counter(
    "mdx_model_cold_starts_total",
    description="Jobs that entered waiting_on_model (endpoint scaling from zero)",
    unit="1",
)
model_waiting_jobs = _meter.create_gauge(
    "mdx_model_waiting_jobs", description="Jobs currently parked on a warming backend", unit="1"
)
model_waiting_oldest_seconds = _meter.create_gauge(
    "mdx_model_waiting_oldest_seconds",
    description="Age of the oldest job waiting on a backend",
    unit="s",
)
model_cost_cents_total = _meter.create_counter(
    "mdx_model_cost_cents_total",
    description="Estimated model cost in cents by backend and tier (daily rate = increase over 1d)",
    unit="1",
)
model_keepwarm_probes_total = _meter.create_counter(
    "mdx_model_keepwarm_probes_total",
    description="Scheduled keep-warm probes by backend and outcome",
    unit="1",
)
