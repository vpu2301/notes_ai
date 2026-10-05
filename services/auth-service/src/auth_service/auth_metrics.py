"""The three auth counters, in one place.

They were declared inside ``routers/login.py`` when that router was the
only way in or out. IDX-M1's native session routes have to feed the same
series — ``AuthRefreshReplay`` in
``infra/prometheus/rules/auth-audit.yml`` alerts on
``increase(mdx_auth_refresh_replay_total[5m]) > 0``, and an alert that
stops seeing replays because the code that detects them moved file is
worse than no alert at all.

Declaring the same instrument name twice in one process is also how you
get two instruments exporting one series, so they live here and both
routers import them.
"""

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

# IDX-A2 named this one; IDX-M2 is what finally emits it. Labelled by
# outcome rather than by tenant: "how often does switching fail, and how"
# is an operational question, "who switched where" is the audit trail's.
token_switch_counter = _meter.create_counter(
    "mdx_auth_token_switch_total",
    description="Workspace-scoped token mints by outcome",
    unit="1",
)

# Sprint 19: fake-door leads from the shared page's CTA (POST /auth/leads).
leads_captured_counter = _meter.create_counter(
    "mdx_leads_captured_total",
    description="Lead e-mails captured on /join (label: ref_present)",
    unit="1",
)
