"""Sprint 19 loop counters, in one place (the ``auth_metrics`` pattern).

Declared at module level rather than on ``ServiceState`` so the routers
that count — sharing and the anonymous page — need nothing new wired
into the state object, in production or in the router tests' fakes.
Names are what ``infra/grafana/dashboards/viral-loop.json`` and
``infra/prometheus/rules/viral-loop.yml`` query; keep them stable.
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
rate_limited = _meter.create_counter(
    "mdx_shared_rate_limit_total",
    description="429s on /v1/shared/* (label: scope)",
    unit="1",
)

# Sprint 20: the interactive page.
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

# Sprint 22: recipient links sent from the product.
recipient_mail_sent = _meter.create_counter(
    "mdx_recipient_mail_sent_total",
    description="Recipient-link mails by outcome (sent, rejected, failed)",
    unit="1",
)

# Sprint 23: verification, abuse, retention.
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
share_retention_cleared = _meter.create_counter(
    "mdx_share_retention_cleared_total",
    description="Rows cleared by the retention job (label: kind)",
    unit="1",
)
