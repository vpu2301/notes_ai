# Runbook — External sharing (recipient loop), GA

Covers Sprints 19–23. Related: `docs/runbooks/notes.md` (recipient
links, responses, product mail), `docs/runbooks/sharing-dsar.md`,
`docs/product/loop-metrics.md`, ADR-0048/0049/0050.

## Flags

| Flag | Default | Off means |
|---|---|---|
| `MDX_EXTERNAL_SHARING_ENABLED` | true | no recipient/public links can be created; recipient pages answer 404; clients hide "Share with client…" |
| `MDX_RECIPIENT_ACTIONS_ENABLED` | true | the page reads; confirm/dispute/flag answer 403 `actions_disabled` |
| `MDX_SIGNUP_ENABLED` | dev true / prod false | `/join` shows the lead form instead of signup |
| `MDX_SHARE_MAIL_*_PER_DAY` | 3 / 50 / 200 | caps on product-sent mail |

Workspace-level policy (`GET/PUT /v1/admin/sharing/policy`, web
`/settings/workspace`) sits under the flags; a flag off wins.

## Rollout stages and exit criteria

1. **Internal** — every flag on for the dev tenant. Exit: the unit and
   integration suites, `check-rls`, `check-notification-pii-free` green;
   an end-to-end demo through real SMTP.
2. **Alpha** — three friendly SME workspaces, two weeks. Exit: zero
   cross-tenant findings; dispute rate < 10 %; abuse reports < 1 per
   1 000 views; p95 of `GET /v1/shared/{token}` ≤ 300 ms at 50 rps
   (`docs/testing/load/`); no product-mail failure rate > 1 %.
3. **Pilot** — every self-serve tenant. Exit: the same, plus loop
   efficiency measured over ≥ 300 first views (concept doc kill
   criteria: CTA CTR < 1 % or dispute rate > 20 % stops the rollout).
4. **GA** — flags default on in prod; policy defaults unchanged.

## Alerts

`infra/prometheus/rules/viral-loop.yml`: `SharedPageRateLimitHigh`,
`SharedPageDisputeRateHigh`, `SharedPageReportsHigh`, `SharedPageOtpBurst`.

### Abuse reports

`SharedPageReportsHigh`: read `share_abuse_reports` (per tenant, with
`reason`) and the `note.link_reported` audit rows. Three `spam` reports
against one sender's links switch that workspace's product mail off
(`sharing_policy.auto_disabled_reason = abuse_reports`); the admin
re-enables it from `/settings/workspace`. Revoke the sender's links with
`DELETE /v1/notes/{id}/links` if the reports are founded.

### Verification codes

`SharedPageOtpBurst`: codes are mailed inline; the per-link cap is 3 per
hour (`note:shared-rl:otp:*`). A burst across many links is a client
retry loop or a relay attempt — check `note.recipient_verification_requested`
audit rows per tenant and the SMTP provider's log.

## Operating cadence

Weekly loop review on the funnel CSV (`scripts/jobs/weekly_funnel.py`)
and the Grafana "Viral loop" dashboard; decisions go to
`docs/product/loop-decisions.md`.

## GA checklist

- [ ] Migrations 0035–0041 applied; `funnel_reader` present; retention and funnel crons scheduled
- [ ] `MDX_API_PUBLIC_BASE_URL` and `MDX_APP_BASE_URL` set to public hostnames; `/v1/shared/*` reachable
- [ ] Real SMTP for `MDX_NOTE_SMTP_*` (recipient mail, codes) and `MDX_AUTH_SMTP_*` (signup codes)
- [ ] Load run recorded under `docs/testing/load/`; axe spec green in both themes
- [ ] Privacy page copy (`/s/privacy`) reviewed by legal
- [ ] Alerts wired to a channel someone reads; dispute-rate kill signal understood by product
