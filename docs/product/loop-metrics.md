# Loop metrics — definitions (Sprints 19–22)

Every number below is a count on a closed vocabulary; nothing here
identifies a recipient. Sources are the audit kinds in
`docs/audit/event-kinds.md`, the Prometheus counters, and the weekly
cohort (`scripts/ops/loop_funnel.sql`, read as `funnel_reader`).

| Metric | Definition | Source | Target (concept doc) |
|---|---|---|---|
| External share rate | notes with ≥1 recipient link / finalized notes | cohort `notes_with_recipient_link / notes_finalized` | ≥ 5 % (kill signal below) |
| Links sent | recipient links the product mailed (`delivery_status = sent`) | cohort `links_sent`; `mdx_recipient_mail_sent_total{outcome}` | — |
| First views | links opened at least once | `first_viewed_at`; `mdx_shared_views_total{first_view="true"}` | — |
| Sent → opened | first views / links sent | cohort | delivery quality; compare product-sent vs copied |
| Recipient action rate | links with ≥1 live response / first views | cohort `links_responded / first_viewed`; `mdx_shared_responses_total` | H2 |
| Dispute rate | disputes / (confirms + dones + disputes) | `mdx_shared_responses_total{kind}`; admin stats `dispute_rate` | ≤ 10 %; > 20 % over 7 d = stop scaling |
| CTA CTR | CTA clicks / first views | `cta_clicked_at`; `mdx_shared_cta_clicks_total` | ≥ 3 % builds Sprint 21; < 1 % stops it |
| Leads | `/join` addresses left | `referrals.lead_email`; `mdx_leads_captured_total` | — |
| Referred signups | signups carrying a `ref` | `referrals.referred_sub`; `mdx_auth_signup_referred_total{stage="requested"}` | — |
| Verified workspaces | referred signups that spent the code | `referrals.referred_tenant_id`; `…{stage="verified"}` | — |
| Activated (7 d) | verified workspaces with a finalized note within 7 days | cohort `activated_7d` | — |
| **Loop efficiency** | verified referred workspaces per 100 first views | cohort `loop_efficiency_pct` | ≥ 2 per 100 |
| Opt-out rate | unsubscribes / links sent | `note.recipient_unsubscribed` audit; `opted_out` in admin stats | guardrail ≤ 2 % |
| Nudge acceptance | links created with `source = nudge` / finalizes from the Mac | `note.link_created{source}` audit | measured separately |

The weekly CSV (`scripts/jobs/weekly_funnel.py`, `funnel-YYYY-WW.csv`)
is the artefact for the product cadence; the Grafana "Viral loop"
dashboard shows the same numbers live.
