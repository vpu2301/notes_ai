"""Auth counters, declared once (Prometheus alerts depend on these names; two declarations = two instruments)."""

from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("mdx.auth")

login_counter = _meter.create_counter(
    "mdx_auth_login_total",
    description="Login attempts by outcome",
    unit="1",
)
refresh_replay_counter = _meter.create_counter(
    "mdx_auth_refresh_replay_total",
    description="Refresh-token replays detected (always anomalous)",
    unit="1",
)
logout_counter = _meter.create_counter(
    "mdx_auth_logout_total",
    description="Logout calls",
    unit="1",
)

# Labelled by outcome, not tenant.
token_switch_counter = _meter.create_counter(
    "mdx_auth_token_switch_total",
    description="Workspace-scoped token mints by outcome",
    unit="1",
)

# Leads from the shared page's CTA (POST /auth/leads).
leads_captured_counter = _meter.create_counter(
    "mdx_leads_captured_total",
    description="Lead e-mails captured on /join (label: ref_present)",
    unit="1",
)
