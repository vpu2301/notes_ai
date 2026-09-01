# ADR-0031 — Notification email carries pointers, never content

**Status:** Accepted (Sprint 12) — **DPO sign-off required on every template diff**

## Context

Email leaves our trust boundary. It traverses relays we do not control,
lands in mailboxes we do not control, and is retained indefinitely by
both. Tenants trust us with confidential meeting content and personal
data under GDPR.

## Decision

A notification email contains a **note code and a deep link**. It
never contains note content, transcript text, personal names, or any
other note-derived data. This is a **permanent boundary, not a
deferral**.

Enforcement is an **allow-list**, not a scrubber:
`domain/render.ALLOWED_PAYLOAD_KEYS` names, per category, the only
payload keys any template may read. Everything else is invisible to
rendering no matter what a producer sends.

## Rationale

Scrubbing is a losing game. A scrubber removes the patterns someone
thought of; a Ukrainian surname is not a pattern, and neither is a
free-text business detail. The sprint-10 PII scrubber is appropriate
for *telemetry*, where the alternative is dropping the data entirely —
but for an outbound channel the burden should be inverted. With an
allow-list, a producer that adds a personal-name key to a payload finds
it silently unused, and surfacing it requires an explicit edit to a
named list that shows up in the diff a DPO reviews.

Note **titles** are deliberately excluded even though they look
innocuous: an author-written title routinely contains confidential
detail (a deal name, a candidate, a restructuring), and the title would
land in a subject line.

## Consequences

- `scripts/ci/check-notification-pii-free.py` is a **blocking** CI gate.
  It renders every emailing category against a payload stuffed with fake
  sensitive data and fails if any token survives — and fails if the note
  code is *missing*, since a mail with no pointer is not actionable.
- Emails are less informative by design. A user must open the system to
  learn anything substantive. That is the intended trade.
- `notifications.render_fields` persists the allow-listed projection so
  the email channel re-renders from the same pointers. This is not a
  hole in the boundary: it holds exactly what the allow-list admitted.
- The gate's token list must avoid common nouns, which occur in
  legitimate boilerplate; a gate that always fails gets muted.
- Adding a payload key to an allow-list entry requires DPO sign-off.
