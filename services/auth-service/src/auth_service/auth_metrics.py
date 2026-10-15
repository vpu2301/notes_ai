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

# W1: activations only (a borrowed token is not a switch); labelled by outcome, not tenant.
workspace_switch_counter = _meter.create_counter(
    "mdx_auth_workspace_switch_total",
    description="Workspace switches (POST /auth/token activate=true) by outcome",
    unit="1",
)
personal_healed_counter = _meter.create_counter(
    "mdx_auth_personal_healed_total",
    description="Personal workspaces created for an identity that had none",
    unit="1",
)
# The W4 gate for dropping `db_user`: who still gets it, and from which source.
me_legacy_db_user_counter = _meter.create_counter(
    "mdx_auth_me_legacy_db_user_total",
    description="GET /auth/me responses carrying db_user (labels: client, source)",
    unit="1",
)

# W2: the invitation funnel. `has_account` is true|false|unknown, never an address.
invitation_counter = _meter.create_counter(
    "mdx_auth_invitation_total",
    description="Workspace invitations by action (labels: action, has_account)",
    unit="1",
)
workspace_created_counter = _meter.create_counter(
    "mdx_auth_workspace_created_total",
    description="Team workspaces created (label: source)",
    unit="1",
)
workspace_dissolved_counter = _meter.create_counter(
    "mdx_auth_workspace_dissolved_total",
    description="Team workspaces dissolved by their owner",
    unit="1",
)
member_left_counter = _meter.create_counter(
    "mdx_auth_member_left_total",
    description="Members who left a workspace themselves",
    unit="1",
)

# Leads from the shared page's CTA (POST /auth/leads).
leads_captured_counter = _meter.create_counter(
    "mdx_leads_captured_total",
    description="Lead e-mails captured on /join (label: ref_present)",
    unit="1",
)
