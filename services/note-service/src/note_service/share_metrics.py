"""Sharing loop counters, at module level so routers need nothing wired into state.
Names are queried by infra/grafana/dashboards/viral-loop.json and
infra/prometheus/rules/viral-loop.yml; keep them stable.
"""

from __future__ import annotations

from opentelemetry import metrics

_meter = metrics.get_meter("mdx.note.share")

links_created = _meter.create_counter(
    "mdx_share_links_created_total",
    description="Share links minted (label: kind)",
    unit="1",
)
shared_views = _meter.create_counter(
    "mdx_shared_views_total",
    description="Anonymous reads of a shared note (labels: kind, first_view)",
    unit="1",
)
cta_clicks = _meter.create_counter(
    "mdx_shared_cta_clicks_total",
    description="Clicks on the shared page's product CTA",
    unit="1",
)
# W1 baseline for W2/W3 (`share.blocked_no_account`): a share by e-mail refused because
# nobody in this workspace has the address. Counts only — never the address.
# W3: per-note grants by role; `kind` granted (member) | invited (guest, via auth-service).
share_total = _meter.create_counter(
    "mdx_note_share_total",
    description="Per-note grants (labels: role, kind)",
    unit="1",
)
share_blocked_no_account = _meter.create_counter(
    "mdx_share_blocked_no_account_total",
    description="Shares to a person refused because they are not a workspace member",
    unit="1",
)
rate_limited = _meter.create_counter(
    "mdx_shared_rate_limit_total",
    description="429s on /v1/shared/* (label: scope)",
    unit="1",
)

# The interactive page.
action_items_materialised = _meter.create_counter(
    "mdx_action_items_materialised_total",
    description="Action items derived from the note text (labels: parsed_owner, parsed_due)",
    unit="1",
)
shared_responses = _meter.create_counter(
    "mdx_shared_responses_total",
    description="Recipient responses on items (label: kind)",
    unit="1",
)
shared_flags = _meter.create_counter(
    "mdx_shared_flags_total",
    description="Recipient section flags",
    unit="1",
)

# Recipient links sent from the product.
recipient_mail_sent = _meter.create_counter(
    "mdx_recipient_mail_sent_total",
    description="Recipient-link mails by outcome (sent, rejected, failed)",
    unit="1",
)

# Verification, abuse, retention.
share_otp_requests = _meter.create_counter(
    "mdx_share_otp_requests_total",
    description="Recipient verification codes requested",
    unit="1",
)
share_abuse_reports = _meter.create_counter(
    "mdx_share_abuse_reports_total",
    description="Reports from the shared page (label: reason)",
    unit="1",
)
