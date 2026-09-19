# ADR-0050 — Workspace sharing policy lives on the tenant; the product line is the price of the free tier

**Status:** Accepted · **Date:** 2026-09-17 · **Sprint:** 23 (recipient viral loop, GA)

## Context

IT and privacy objections are the top churn and legal risk in this
category. A workspace admin needs to say how notes leave the workspace
without a release, and a recipient needs to know what the page collects.
At the same time the header line on the shared page is what powers the
loop: a free workspace that could switch it off would be a free
workspace with no reason to ever pay.

## Decision

1. **Policy as JSON on the tenant row** (`tenants.sharing_policy`,
   migration 0041), validated by `domain/sharing_policy.py`; `{}` is
   every default, so nothing changes for a workspace that never opens
   the settings page. Read on the tenant-scoped connection and cached in
   process for 60 s; written only through a SECURITY DEFINER helper that
   refuses any tenant but the connection's own. No pub/sub: "visible
   within a minute" is the bar and the value changes rarely.
2. **Clip, don't refuse**, where a number is involved: `max_link_days`
   shortens a request. Switches refuse with a machine code
   (`external_sharing_disabled`, `public_links_disabled`,
   `product_email_disabled`). *(`require_finalized` was retired with
   the finalize lifecycle — ADR-0051.)*
3. **The product line can be turned off only on a paid plan** (G-1).
   Free and legacy workspaces always carry it. The policy may store
   `cta_enabled = false` on a free plan; the page ignores it.
4. **Verified recipients are per link.** A six-digit code is mailed
   inline (no outbox — ADR-0049), hashed with the suppression pepper and
   the link id, five attempts, ten minutes. Reading never needs it;
   acting does. Whoever controls the mailbox is the recipient.
5. **"What changed" is keys, not prose.** The page compares the version
   the link last loaded with the current one through the existing diff
   engine and returns section and item keys; amendment reasons never
   reach a recipient.
6. **Deployment flags beat workspace policy**: `MDX_EXTERNAL_SHARING_ENABLED`
   (off → recipient links 404), `MDX_RECIPIENT_ACTIONS_ENABLED` (off →
   read-only page). Stages: internal → alpha → pilot → GA, gated on the
   criteria in `docs/runbooks/external-sharing.md`.
7. **Retention is a nightly job**, not a trigger: 30 days after a link
   expires its responses are cleared, the address dropped and any code
   deleted. Abuse reports feed a guard that switches a workspace's
   product mail off after three `spam` reports against one sender.

## Consequences

- The anonymous surface is world-readable by design and now says so in
  CORS: `/v1/shared/*` answers any origin without credentials; the
  credentialed allow-list stays for everything else.
- Tightening a policy revokes nothing by itself; the admin has an
  explicit "turn off every link" that audits per note.
