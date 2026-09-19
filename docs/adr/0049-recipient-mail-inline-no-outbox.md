# ADR-0049 — Recipient links are mailed inline by note-service; opt-out is a global hashed suppression

**Status:** Accepted · **Date:** 2026-09-17 · **Sprint:** 22 (recipient viral loop)

## Context

Sprint 22's brief describes a `share_mail_outbox` with a delivery worker,
retry backoff, a "secret destroyed after send" CHECK and a nightly purge —
the shape auth-service uses for password mail. note-service already
sends share mail a different way: `/share/email` (sprint 16) renders and
delivers inline through `adapters/email.py`, bounded by a timeout, with
the outcome returned to the sender in the same response.

## Decision

1. **Inline, not outbox.** `POST /v1/notes/{id}/links/{link_id}/send` and
   `POST …/links {send: true}` render and send in the request, record
   `sent` / `failed` (error class only) on the link row, and answer. The
   share URL exists in the request and in the recipient's inbox — never
   at rest. A slow relay costs the sender seconds, the same trade
   sprint 16 made and documented. No worker, no purge job, no
   `secret_fields` invariant to police.
2. **Status lives on the link.** `note_share_links.delivery_status`
   (`not_sent | sent | failed | suppressed`), `sent_at`, `send_count`,
   `last_send_error`. "Opened" and "Responded" come from the Sprint 19/20
   columns already there; the sender's "Opened" chip is pushed by an
   in-app-only notification category (`note.link_status_changed`) on the
   link's first open.
3. **Opt-out is global and hashed.** `share_mail_suppressions` stores
   `sha256(pepper || lower(email))` and a reason, nothing else, and is
   reachable from a tenant-scoped connection only through two
   SECURITY DEFINER helpers (the 0016 resolver pattern). The unsubscribe
   URL carries `base64(link id).hmac` — no address, no login — and the
   page is identical for a valid and a forged signature.
4. **The mail carries pointers only** (ADR-0031): sender display name,
   workspace name, expiry, the product line, the sender's personal
   message as text, the link, the opt-out. No note title, no section
   text. Enforced by a test with a sentinel title.
5. **Caps** per link (3/day), sender (50/day) and workspace (200/day)
   on the house fixed-window limiter, fail-open like every other
   note-service limiter.
6. **The funnel is read by a role, not a service.** `funnel_reader`
   (0040) has SELECT-only policies on the five tables the cohort query
   joins; Grafana and the weekly CSV job connect as it.

## Consequences

- No bounce handling: with SMTP only, a hard bounce arrives in the
  sender's reply-to mailbox. `hard_bounce` exists as a suppression
  reason for an operator to record it.
- The macOS post-meeting nudge cannot pre-fill attendee addresses:
  calendar events reach the clients as attendee *names* by design. It
  offers the sheet, and sends nothing until the sender does.
